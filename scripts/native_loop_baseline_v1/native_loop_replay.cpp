// AQUA-FE input adapter. Native VINS BRIEF/PnP and graph solver are compiled
// unchanged except for the explicit candidate routing/diagnostic hooks.
#include "candidate_bridge.h"
#include "pose_graph.h"
#include <fstream>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <sys/stat.h>

camodocal::CameraPtr m_camera;
Eigen::Vector3d tic;
Eigen::Matrix3d qic;
ros::Publisher pub_match_img;
int VISUALIZATION_SHIFT_X = 0, VISUALIZATION_SHIFT_Y = 0, ROW = 600, COL = 800, DEBUG_IMAGE = 0;
std::string BRIEF_PATTERN_FILE, POSE_GRAPH_SAVE_PATH, VINS_RESULT_PATH;

namespace {
bool learned = false;
std::vector<double> times;
std::map<int, int> selected;
std::ofstream bow_log, geometry_log;
std::atomic<int> optimized_through{-1};

std::vector<std::string> split(const std::string &line) {
    // These inputs are machine-generated numeric CSVs with comma-free paths.
    if (line.find('"') != std::string::npos) throw std::runtime_error("Quoted CSV not supported in native adapter");
    std::vector<std::string> result;
    std::stringstream stream(!line.empty() && line.back() == '\r' ? line.substr(0, line.size() - 1) : line);
    std::string part;
    while (std::getline(stream, part, ',')) result.push_back(part);
    return result;
}

double headerTime(const std::string &ns_text) {
    const auto ns = std::stoll(ns_text);
    if (ns <= 0) throw std::runtime_error("Invalid header nanoseconds");
    return double(ns / 1000000000LL) + double(ns % 1000000000LL) * 1e-9;
}

void loadCandidates(const std::string &file, const std::string &sequence, const std::string &repeat) {
    std::ifstream stream(file);
    if (!stream) throw std::runtime_error("Missing learned candidate CSV");
    std::string line;
    std::getline(stream, line);
    const auto header = split(line);
    std::map<std::string, size_t> cols;
    for (size_t i = 0; i < header.size(); ++i) cols[header[i]] = i;
    for (auto name : {"query_id", "query_time_s", "candidate_id", "candidate_time_s", "selected_for_geometry", "arm", "sequence_id", "repeat"})
        if (!cols.count(name)) throw std::runtime_error("Missing candidate identity column");
    while (std::getline(stream, line)) {
        if (line.empty()) continue;
        auto row = split(line);
        if (row.size() != header.size()) throw std::runtime_error("Malformed candidate CSV");
        if (row[cols["arm"]] != "L" || row[cols["sequence_id"]] != sequence || row[cols["repeat"]] != repeat)
            throw std::runtime_error("Candidate arm/sequence/repeat mismatch");
        const int q = std::stoi(row[cols["query_id"]]), c = std::stoi(row[cols["candidate_id"]]);
        if (q < 0 || q >= int(times.size()) || c < 0 || c >= q - 50)
            throw std::runtime_error("Candidate outside frozen past history");
        if (std::stod(row[cols["query_time_s"]]) != times[q] || std::stod(row[cols["candidate_time_s"]]) != times[c])
            throw std::runtime_error("Candidate/archive header identity mismatch");
        if (row[cols["selected_for_geometry"]] == "1") {
            if (selected.count(q)) throw std::runtime_error("More than one geometric candidate per query");
            selected[q] = c;
        }
    }
}
}

bool aquaLearnedMode() { return learned; }
int aquaLearnedCandidate(int query, double time) {
    if (time != times.at(query)) throw std::runtime_error("Live keyframe roster mismatch");
    auto found = selected.find(query);
    return found == selected.end() ? -1 : found->second;
}
void aquaRecordBow(int query, double time, const DBoW2::QueryResults &results) {
    bool gate = results.size() > 1 && results[0].Score > .05;
    bool secondary = false;
    for (size_t i = 1; i < results.size(); ++i) secondary |= results[i].Score > .015;
    gate &= secondary;
    int choice = -1;
    for (const auto &r : results) {
        if (int(r.Id) >= query - 50) throw std::runtime_error("DBoW history exception was not removed");
        if (gate && r.Score > .015 && (choice < 0 || int(r.Id) < choice)) choice = int(r.Id);
    }
    for (size_t i = 0; i < results.size(); ++i) {
        const auto &r = results[i];
        bow_log << query << ',' << time << ',' << r.Id << ',' << times.at(r.Id) << ',' << i + 1 << ','
                << r.Score << ',' << gate << ',' << (int(r.Id) == choice) << '\n';
    }
}
void aquaRecordVerification(KeyFrame *frame, int candidate, bool passed, double seconds) {
    geometry_log << frame->index << ',' << frame->time_stamp << ',' << candidate << ','
                 << (passed ? "PASS" : "REJECT") << ',' << seconds << ",Unknown";
    for (int i = 0; i < 8; ++i) {
        geometry_log << ',';
        if (passed) geometry_log << frame->loop_info[i];
    }
    geometry_log << '\n';
}
void aquaOptimizationDone(int index) { optimized_through.store(index, std::memory_order_release); }

int main(int argc, char **argv) {
    if (argc != 10 && argc != 11) {
        std::cerr << "usage: aqua_native_loop_replay ARCHIVE CAMERA_YAML VINS_YAML BRIEF_VOCAB BRIEF_PATTERN OUTDIR C|L SEQUENCE REPEAT [L_CANDIDATES_CSV]\n";
        return 64;
    }
    try {
        const std::string archive = argv[1], output = argv[6], arm = argv[7];
        learned = arm == "L";
        if ((arm != "C" && arm != "L") || (learned && argc != 11) || (!learned && argc != 10))
            throw std::runtime_error("Invalid arm/candidate arguments");
        std::ifstream receipt(archive + "/archive_receipt.json");
        if (!receipt) throw std::runtime_error("Incomplete archive: missing receipt");
        std::ifstream roster_file(archive + "/keyframes.csv");
        std::string line;
        std::getline(roster_file, line);
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (line != "id,timestamp_ns,tx,ty,tz,qw,qx,qy,qz,image,points,point_count,image_sha256,points_sha256")
            throw std::runtime_error("Archive roster schema mismatch");
        std::vector<std::vector<std::string>> roster;
        while (std::getline(roster_file, line)) {
            auto row = split(line);
            if (row.size() != 14 || std::stoi(row[0]) != int(roster.size())) throw std::runtime_error("Invalid archive index");
            const double stamp = headerTime(row[1]);
            if (!times.empty() && stamp <= times.back()) throw std::runtime_error("Non-increasing keyframe times");
            times.push_back(stamp);
            roster.push_back(row);
        }
        if (roster.empty()) throw std::runtime_error("Empty native roster");
        if (learned) loadCandidates(argv[10], argv[8], argv[9]);
        m_camera = camodocal::CameraFactory::instance()->generateCameraFromYamlFile(argv[2]);
        if (!m_camera) throw std::runtime_error("Camera model loading failed");
        cv::FileStorage config(argv[3], cv::FileStorage::READ);
        cv::Mat transform;
        config["body_T_cam0"] >> transform;
        if (transform.rows != 4 || transform.cols != 4 || transform.type() != CV_64F)
            throw std::runtime_error("Missing body_T_cam0; do not guess extrinsics");
        for (int i = 0; i < 3; ++i) {
            tic[i] = transform.at<double>(i, 3);
            for (int j = 0; j < 3; ++j) qic(i, j) = transform.at<double>(i, j);
        }
        if (::mkdir(output.c_str(), 0755) != 0) throw std::runtime_error("Output must be a new directory under an existing parent");
        POSE_GRAPH_SAVE_PATH = output + "/";
        VINS_RESULT_PATH = output + "/native_path_updates.csv";
        BRIEF_PATTERN_FILE = argv[5];
        bow_log.open(output + "/bow_candidates.csv");
        geometry_log.open(output + "/geometry.csv");
        bow_log << std::setprecision(17) << "query_id,query_time_s,candidate_id,candidate_time_s,rank,score,score_gate,selected_for_geometry\n";
        geometry_log << std::setprecision(17) << "query_id,query_time_s,candidate_id,geometry,verification_s,correctness,tx,ty,tz,qw,qx,qy,qz,yaw_deg\n";
        std::ofstream processing(output + "/processing.csv"), edges(output + "/raw_odometry_edges.csv");
        processing << std::setprecision(17) << "id,brief_construction_s,native_add_keyframe_s\n";
        edges << std::setprecision(17) << "from_id,to_id,tx,ty,tz,yaw_deg,from_pitch_deg,from_roll_deg\n";
        ros::init(argc, argv, "aqua_native_loop_replay", ros::init_options::AnonymousName);
        ros::NodeHandle node("~");
        // Native worker owns its normal optimizer loop. Keep graph alive until
        // process exit rather than destroying it while that worker is running.
        PoseGraph *graph = new PoseGraph();
        graph->registerPub(node);
        graph->loadVocabulary(argv[4]);
        graph->setIMUFlag(true);
        std::vector<KeyFrame *> frames;
        int last_loop = -1;
        for (const auto &row : roster) {
            const int idx = std::stoi(row[0]), count = std::stoi(row[11]);
            if (count < 0 || count > 350) throw std::runtime_error("Invalid map-point count");
            Eigen::Vector3d t(std::stod(row[2]), std::stod(row[3]), std::stod(row[4]));
            Eigen::Quaterniond q(std::stod(row[5]), std::stod(row[6]), std::stod(row[7]), std::stod(row[8]));
            if (!t.allFinite() || !q.coeffs().allFinite() || std::abs(q.norm() - 1) > 1e-6)
                throw std::runtime_error("Invalid archived body pose; do not silently repair it");
            Eigen::Matrix3d rotation = q.toRotationMatrix();
            cv::Mat image = cv::imread(archive + "/" + row[9], cv::IMREAD_GRAYSCALE);
            if (image.rows != ROW || image.cols != COL) throw std::runtime_error("Image missing or wrong frozen dimensions");
            std::ifstream point_file(archive + "/" + row[10], std::ios::binary);
            if (!point_file) throw std::runtime_error("Missing native point file");
            std::vector<cv::Point3f> world;
            std::vector<cv::Point2f> pixel, normalized;
            std::vector<double> ids;
            for (int i = 0; i < count; ++i) {
                float p[8];
                if (!point_file.read(reinterpret_cast<char *>(p), sizeof(p))) throw std::runtime_error("Truncated native points");
                for (float v : p) if (!std::isfinite(v)) throw std::runtime_error("Nonfinite observation");
                world.emplace_back(p[0], p[1], p[2]); normalized.emplace_back(p[3], p[4]);
                pixel.emplace_back(p[5], p[6]); ids.push_back(p[7]);
            }
            if (point_file.peek() != std::ifstream::traits_type::eof()) throw std::runtime_error("Extra native point bytes");
            const auto begin = std::chrono::steady_clock::now();
            KeyFrame *frame = new KeyFrame(times[idx], idx, t, rotation, image, world, pixel, normalized, ids, 1);
            const auto after_brief = std::chrono::steady_clock::now();
            // Record exactly the raw four-predecessor odometry measurements
            // from which native optimize4DoF constructs its non-loop residuals.
            const auto yaw = Utility::R2ypr(rotation);
            for (int delta = 1; delta < 5 && idx - delta >= 0; ++delta) {
                const auto *prior = frames[idx - delta];
                const auto ypr = Utility::R2ypr(prior->origin_vio_R);
                const Eigen::Vector3d relative = prior->origin_vio_R.transpose() * (t - prior->origin_vio_T);
                edges << idx - delta << ',' << idx << ',' << relative.x() << ',' << relative.y() << ',' << relative.z()
                      << ',' << yaw.x() - ypr.x() << ',' << ypr.y() << ',' << ypr.z() << '\n';
            }
            graph->addKeyFrame(frame, true);
            const auto after_add = std::chrono::steady_clock::now();
            processing << idx << ',' << std::chrono::duration<double>(after_brief - begin).count() << ','
                       << std::chrono::duration<double>(after_add - after_brief).count() << '\n';
            frames.push_back(frame);
            if (frame->has_loop) last_loop = idx;
        }
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(120);
        while (optimized_through.load(std::memory_order_acquire) < last_loop) {
            if (std::chrono::steady_clock::now() > deadline) throw std::runtime_error("Native graph did not finish its last queued loop");
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        }
        std::ofstream global(output + "/global_body.tum"), local(output + "/local_body.tum");
        global << std::setprecision(17); local << std::setprecision(17);
        for (auto *frame : frames) {
            Eigen::Vector3d t; Eigen::Matrix3d r;
            frame->getPose(t, r); Eigen::Quaterniond q(r), raw_q(frame->origin_vio_R);
            global << frame->time_stamp << ' ' << t.transpose() << ' ' << q.x() << ' ' << q.y() << ' ' << q.z() << ' ' << q.w() << '\n';
            local << frame->time_stamp << ' ' << frame->origin_vio_T.transpose() << ' ' << raw_q.x() << ' ' << raw_q.y() << ' ' << raw_q.z() << ' ' << raw_q.w() << '\n';
        }
        std::cout << "NATIVE_REPLAY_FINISHED keyframes=" << frames.size() << " last_verified_loop=" << last_loop
                  << " optimized_through=" << optimized_through.load() << '\n';
        ros::shutdown();
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "NATIVE_REPLAY_INVALID " << error.what() << '\n';
        return 1;
    }
}
