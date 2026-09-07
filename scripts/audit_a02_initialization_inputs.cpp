// Read-only numerical diagnostic. Link the existing, hash-locked VINS library;
// do not compile VINS sources or run Estimator, GlobalSFM, IMU alignment or BA.
// Stop at the FIRST successful relativePose step: beyond that point an unlogged
// SFM failure could change marginalization, so a shadow state is not justified.
#include <json/json.h>
#include <rosbag/bag.h>
#include <rosbag/view.h>
#include <sensor_msgs/PointCloud.h>
#include "estimator/feature_manager.h"
#include "initial/solve_5pts.h"

using Frame = map<int, vector<pair<int, Eigen::Matrix<double, 8, 1>>>>;

struct Snapshot {
    Json::Value trace{Json::arrayValue};
    list<FeaturePerId> features;
    vector<pair<Vector3d, Vector3d>> relative_pairs;
    vector<int> relative_ids;
    int frame = -1, left = -1;
    Matrix3d rotation;
    Vector3d translation;
    vector<int> window;
};

Json::Value ints(const vector<int>& input) {
    Json::Value out(Json::arrayValue);
    for (int value : input) out.append(value);
    return out;
}

Snapshot inspect(const string& path) {
    Matrix3d rotations[WINDOW_SIZE + 1];
    for (auto& r : rotations) r.setIdentity();
    FeatureManager manager(rotations);
    MotionEstimator motion;
    int frame_count = 0, output = -1;
    double initial_timestamp = 0;
    vector<int> window(WINDOW_SIZE + 1, -1);
    Snapshot result;
    rosbag::Bag bag(path, rosbag::bagmode::Read);
    rosbag::View view(bag, rosbag::TopicQuery(string("/feature_tracker/feature")));
    for (const auto& instance : view) {
        auto msg = instance.instantiate<sensor_msgs::PointCloud>();
        if (!msg) throw runtime_error("Unexpected message type");
        ++output;
        if (output > 40) throw runtime_error("Bounded prefix ended without relative pose");
        Frame image;
        for (size_t i = 0; i < msg->points.size(); ++i) {
            const auto& p = msg->points[i];
            if (p.z != 1) throw runtime_error("Unexpected normalized point");
            double quality = 1.0;
            for (const auto& channel : msg->channels)
                if (channel.name == "quality") quality = max(.05, min(1., double(channel.values.at(i))));
            Eigen::Matrix<double, 8, 1> point;
            point << p.x, p.y, p.z, msg->channels[2].values.at(i), msg->channels[3].values.at(i),
                msg->channels[4].values.at(i), msg->channels[5].values.at(i), quality;
            image[int(msg->channels[0].values.at(i))].emplace_back(int(msg->channels[1].values.at(i)), point);
        }
        bool keyframe = manager.addFeatureCheckParallax(frame_count, image, TD);
        window[frame_count] = output;
        double header = msg->header.stamp.toSec();
        Json::Value row;
        row["output_frame"] = output;
        // String prevents downstream JSON/JavaScript 53-bit rounding of ns.
        row["header_ns"] = std::to_string(msg->header.stamp.toNSec());
        row["keyframe"] = keyframe;
        row["new_features"] = manager.new_feature_num;
        row["tracked_features"] = manager.last_track_num;
        row["long_features"] = manager.long_track_num;
        row["parallax_px"] = manager.last_average_parallax;
        row["attempt"] = false;
        bool success = false;
        if (frame_count == WINDOW_SIZE && header - initial_timestamp > 0.1) {
            row["attempt"] = true;
            initial_timestamp = header;
            for (int left = 0; left < WINDOW_SIZE; ++left) {
                auto pairs = manager.getCorresponding(left, WINDOW_SIZE);
                if (pairs.size() <= 20) continue;
                double sum = 0;
                for (const auto& pair : pairs) sum += (pair.first.head<2>() - pair.second.head<2>()).norm();
                if (sum / pairs.size() * 460 <= 30) continue;
                if (!motion.solveRelativeRT(pairs, result.rotation, result.translation)) continue;
                success = true;
                result.frame = output;
                result.left = left;
                result.relative_pairs = pairs;
                for (auto& f : manager.feature)
                    if (f.start_frame <= left && f.endFrame() >= WINDOW_SIZE)
                        result.relative_ids.push_back(f.feature_id);
                break;
            }
        }
        row["relative_success"] = success;
        row["window_output_frames"] = ints(vector<int>(window.begin(), window.begin() + frame_count + 1));
        result.trace.append(row);
        if (success) {
            for (const auto& f : manager.feature) result.features.push_back(f);
            result.window = window;
            bag.close();
            return result;
        }
        if (frame_count == WINDOW_SIZE) {
            if (keyframe) {
                manager.removeBack();
                for (int i = 0; i < WINDOW_SIZE; ++i) window[i] = window[i + 1];
            } else {
                manager.removeFront(frame_count);
                window[WINDOW_SIZE - 1] = window[WINDOW_SIZE];
            }
        } else ++frame_count;
    }
    throw runtime_error("Bag ended before relative pose");
}

int main(int argc, char** argv) {
    if (argc != 4) throw runtime_error("Usage: audit KLT.bag DELETE.bag canonical.yaml");
    ros::Time::init();
    cv::FileStorage config(argv[3], cv::FileStorage::READ);
    if (!config.isOpened()) throw runtime_error("Cannot read frozen YAML");
    NUM_OF_CAM = int(config["num_of_cam"]);
    MIN_PARALLAX = double(config["keyframe_parallax"]) / FOCAL_LENGTH;
    TD = double(config["td"]);
    if (NUM_OF_CAM != 1) throw runtime_error("Only frozen mono A02 supported");
    auto baseline = inspect(argv[1]);
    auto deleted = inspect(argv[2]);
    Json::Value out;
    out["scope"] = "First relative-pose success only; no SFM, IMU alignment, BA or VIO replay";
    out["klt_trace"] = baseline.trace;
    out["delete_trace"] = deleted.trace;
    out["klt_first_relative_output"] = baseline.frame;
    out["delete_first_relative_output"] = deleted.frame;
    out["window_frames_equal"] = baseline.window == deleted.window;
    out["relative_ids_equal_in_order"] = baseline.relative_ids == deleted.relative_ids;
    bool pairs_equal = baseline.relative_pairs.size() == deleted.relative_pairs.size();
    if (pairs_equal)
        for (size_t i = 0; i < baseline.relative_pairs.size(); ++i)
            pairs_equal &= (baseline.relative_pairs[i].first == deleted.relative_pairs[i].first &&
                            baseline.relative_pairs[i].second == deleted.relative_pairs[i].second);
    out["relative_coordinates_equal_in_order"] = pairs_equal;
    out["relative_pair_count"] = Json::UInt64(baseline.relative_pairs.size());
    out["relative_rotation_frobenius_difference"] = (baseline.rotation - deleted.rotation).norm();
    out["relative_translation_difference"] = (baseline.translation - deleted.translation).norm();
    out["klt_relative_window_slot"] = baseline.left;
    out["delete_relative_window_slot"] = deleted.left;
    map<int, const FeaturePerId*> other;
    for (auto& f : deleted.features) other[f.feature_id] = &f;
    vector<int> order_a, order_b;
    for (auto& f : deleted.features) order_b.push_back(f.feature_id);
    out["sfm_input_differences"] = Json::Value(Json::arrayValue);
    for (auto& f : baseline.features) {
        order_a.push_back(f.feature_id);
        auto match = other.find(f.feature_id);
        if (match != other.end() && f.start_frame == match->second->start_frame &&
                f.feature_per_frame.size() == match->second->feature_per_frame.size()) continue;
        Json::Value diff;
        diff["id"] = f.feature_id;
        vector<int> a, b;
        for (size_t i = 0; i < f.feature_per_frame.size(); ++i) a.push_back(baseline.window.at(f.start_frame + i));
        if (match != other.end())
            for (size_t i = 0; i < match->second->feature_per_frame.size(); ++i)
                b.push_back(deleted.window.at(match->second->start_frame + i));
        diff["klt_output_frames"] = ints(a);
        diff["delete_output_frames"] = ints(b);
        out["sfm_input_differences"].append(diff);
    }
    out["sfm_feature_order_equal"] = order_a == order_b;
    out["sfm_klt_feature_count"] = Json::UInt64(order_a.size());
    out["sfm_delete_feature_count"] = Json::UInt64(order_b.size());
    int klt_multi = 0, delete_multi = 0, klt_multi_obs = 0, delete_multi_obs = 0;
    vector<int> multi_order_a, multi_order_b;
    for (const auto& f : baseline.features) if (f.feature_per_frame.size() >= 2) {
        ++klt_multi; klt_multi_obs += f.feature_per_frame.size(); multi_order_a.push_back(f.feature_id);
    }
    for (const auto& f : deleted.features) if (f.feature_per_frame.size() >= 2) {
        ++delete_multi; delete_multi_obs += f.feature_per_frame.size(); multi_order_b.push_back(f.feature_id);
    }
    out["sfm_klt_multiframe_tracks"] = klt_multi;
    out["sfm_delete_multiframe_tracks"] = delete_multi;
    out["sfm_klt_multiframe_observations"] = klt_multi_obs;
    out["sfm_delete_multiframe_observations"] = delete_multi_obs;
    Json::Value displaced(Json::arrayValue);
    if (multi_order_a.size() == multi_order_b.size())
        for (size_t i = 0; i < multi_order_a.size(); ++i) if (multi_order_a[i] != multi_order_b[i]) {
            Json::Value item;
            item["index"] = Json::UInt64(i);
            item["klt_id"] = multi_order_a[i]; item["delete_id"] = multi_order_b[i]; displaced.append(item);
        }
    out["sfm_multiframe_order_displacements"] = displaced;
    Json::StreamWriterBuilder writer;
    writer["indentation"] = "";
    cout << Json::writeString(writer, out) << endl;
}
