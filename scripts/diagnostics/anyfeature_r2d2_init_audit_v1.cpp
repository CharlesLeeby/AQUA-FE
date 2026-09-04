#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

#include <opencv2/calib3d.hpp>

#include "FeatureMatcher.h"
#include "Feature_r2d2_128.h"
#include "Frame.h"
#include "Image.h"
#define private public
#include "Initializer.h"
#undef private

using namespace ANYFEATURE_VSLAM;

static double quantile(std::vector<double> values, double q) {
    if (values.empty()) return -1.0;
    std::sort(values.begin(), values.end());
    double pos = q * static_cast<double>(values.size() - 1);
    size_t lo = static_cast<size_t>(std::floor(pos));
    size_t hi = static_cast<size_t>(std::ceil(pos));
    double a = pos - static_cast<double>(lo);
    return values[lo] * (1.0 - a) + values[hi] * a;
}
struct HDiagnostics {
    int inliers = 0;
    int best_good = 0;
    int second_good = 0;
    float best_parallax = -1.0f;
    float d1_d2 = -1.0f;
    float d2_d3 = -1.0f;
    bool svd_ok = false;
    bool ambiguity_ok = false;
    bool parallax_ok = false;
    bool min_good_ok = false;
    bool fraction_ok = false;
};

static HDiagnostics diagnose_h(Initializer& init, const std::vector<bool>& inliers,
                               const mat3f& H) {
    HDiagnostics d;
    d.inliers = static_cast<int>(std::count(inliers.begin(), inliers.end(), true));
    mat3f A = init.K.inverse() * H * init.K;
    Eigen::JacobiSVD<mat3f> svd(A, Eigen::ComputeFullU | Eigen::ComputeFullV);
    const mat3f U = svd.matrixU();
    const mat3f V = svd.matrixV();
    const mat3f Vt = V.transpose();
    const vec3f w = svd.singularValues();
    const float d1 = w(0), d2 = w(1), d3 = w(2);
    d.d1_d2 = d1 / d2;
    d.d2_d3 = d2 / d3;
    d.svd_ok = d.d1_d2 >= 1.00001f && d.d2_d3 >= 1.00001f;
    if (!d.svd_ok) return d;
    const float s = U.determinant() * Vt.determinant();
    const float aux1 = std::sqrt((d1*d1-d2*d2)/(d1*d1-d3*d3));
    const float aux3 = std::sqrt((d2*d2-d3*d3)/(d1*d1-d3*d3));
    const vec4f x1{aux1, aux1, -aux1, -aux1};
    const vec4f x3{aux3, -aux3, aux3, -aux3};
    const float aux_stheta = std::sqrt((d1*d1-d2*d2)*(d2*d2-d3*d3))/((d1+d3)*d2);
    const float ctheta = (d2*d2+d1*d3)/((d1+d3)*d2);
    const vec4f stheta{aux_stheta, -aux_stheta, -aux_stheta, aux_stheta};
    std::vector<mat3f> rotations;
    std::vector<vec3f> translations;
    for (int i = 0; i < 4; ++i) {
        mat3f Rp = mat3f::Identity();
        Rp(0,0)=ctheta; Rp(0,2)=-stheta(i); Rp(2,0)=stheta(i); Rp(2,2)=ctheta;
        rotations.push_back(s * U * Rp * Vt);
        vec3f tp{x1(i), 0.0f, -x3(i)}; tp *= d1-d3;
        vec3f t = U * tp; translations.push_back(t/t.norm());
    }
    const float aux_sphi = std::sqrt((d1*d1-d2*d2)*(d2*d2-d3*d3))/((d1-d3)*d2);
    const float cphi = (d1*d3-d2*d2)/((d1-d3)*d2);
    const vec4f sphi{aux_sphi, -aux_sphi, -aux_sphi, aux_sphi};
    for (int i = 0; i < 4; ++i) {
        mat3f Rp = mat3f::Identity();
        Rp(0,0)=cphi; Rp(0,2)=sphi(i); Rp(1,1)=-1.0f; Rp(2,0)=sphi(i); Rp(2,2)=-cphi;
        rotations.push_back(s * U * Rp * Vt);
        vec3f tp{x1(i), 0.0f, x3(i)}; tp *= d1+d3;
        vec3f t = U * tp; translations.push_back(t/t.norm());
    }
    for (size_t i = 0; i < rotations.size(); ++i) {
        std::vector<vec3f> points;
        std::vector<bool> good;
        float parallax = -1.0f;
        int n = init.CheckRT(rotations[i], translations[i], init.keypoints1, init.keypoints2,
                             init.matches12, inliers, init.K, points, 4.0f * init.sigma2,
                             good, parallax);
        if (n > d.best_good) {
            d.second_good = d.best_good;
            d.best_good = n;
            d.best_parallax = parallax;
        } else if (n > d.second_good) {
            d.second_good = n;
        }
    }
    d.ambiguity_ok = static_cast<float>(d.second_good) < 0.75f * static_cast<float>(d.best_good);
    d.parallax_ok = d.best_parallax >= 1.0f;
    d.min_good_ok = d.best_good > 50;
    d.fraction_ok = static_cast<float>(d.best_good) > 0.9f * static_cast<float>(d.inliers);
    return d;
}

int main(int argc, char** argv) {
    if (argc != 4) {
        std::cerr << "usage: diag SEQUENCE_ROOT FEATURE_SETTINGS OUTPUT_CSV\n";
        return 2;
    }
    const std::string root = argv[1];
    const std::string settings_path = argv[2];
    const std::string output_path = argv[3];

    FeatureMatcher::setDescriptorDistanceThresholds(settings_path);
    auto settings = std::make_shared<FeatureExtractorSettings>(KEYP_R2D2, DESC_R2D2, settings_path);
    std::shared_ptr<FeatureExtractor> extractor =
        std::make_shared<FeatureExtractor_r2d2_128>(4000, settings);
    std::shared_ptr<Vocabulary> vocabulary;

    cv::Mat K = cv::Mat::eye(3, 3, CV_32F);
    K.at<float>(0, 0) = 543.33277341822145f;
    K.at<float>(1, 1) = 542.39877298256602f;
    K.at<float>(0, 2) = 489.02536042247897f;
    K.at<float>(1, 2) = 305.38727712002805f;
    cv::Mat dist(4, 1, CV_32F);
    dist.at<float>(0) = -0.1255945656257394f;
    dist.at<float>(1) = 0.053221287232781606f;
    dist.at<float>(2) = 9.9407002108049296e-05f;
    dist.at<float>(3) = 9.5506609272423491e-05f;

    std::ifstream rgb(root + "/rgb.txt");
    std::ofstream out(output_path);
    if (!rgb || !out) {
        std::cerr << "cannot open input/output\n";
        return 3;
    }
    out << "index,timestamp,event,reference_index,keypoints,octave0,nmatches,"
           "disp_q10_px,disp_median_px,disp_q90_px,H_inliers,F_inliers,E_inliers,"
           "recover_pose_inliers,initializer_success,triangulated,official_SH,official_SF,"
           "official_RH,official_H_inliers,official_F_inliers,official_H_reconstruct,"
           "official_F_reconstruct,official_H_relaxed00,official_F_relaxed00,H_best_good,"
           "H_second_good,H_best_parallax_deg,H_d1_d2,H_d2_d3,H_svd_ok,H_ambiguity_ok,"
           "H_parallax_ok,H_min_good_ok,H_fraction_ok\n";

    bool have_initializer = false;
    std::unique_ptr<Frame> initial;
    std::unique_ptr<Initializer> initializer;
    std::vector<cv::Point2f> prev_matched;
    std::vector<int> matches;
    int reference_index = -1;
    int index = 0;
    std::string line;
    while (std::getline(rgb, line)) {
        if (line.empty()) continue;
        std::istringstream iss(line);
        double timestamp;
        std::string relative;
        if (!(iss >> timestamp >> relative)) return 4;
        Image image(root + "/" + relative);
        image.GetGrayImage(true);
        Frame current(image, timestamp, extractor, vocabulary, K, dist, 0.0f, 0.0f);
        int octave0 = 0;
        for (const auto& kp : current.mvKeysUn) if (kp.octave == 0) ++octave0;

        if (!have_initializer) {
            if (current.mvKeys.size() > 100) {
                initial = std::make_unique<Frame>(current);
                reference_index = index;
                prev_matched.resize(current.mvKeysUn.size());
                for (size_t i = 0; i < current.mvKeysUn.size(); ++i)
                    prev_matched[i] = current.mvKeysUn[i].pt;
                initializer = std::make_unique<Initializer>(current, 1.0f, 200);
                matches.assign(current.mvKeysUn.size(), -1);
                have_initializer = true;
                out << index << ',' << std::setprecision(17) << timestamp
                    << ",set_reference," << reference_index << ',' << current.mvKeys.size()
                    << ',' << octave0 << ",-1,-1,-1,-1,-1,-1,-1,-1,0,0,-1,-1,-1,-1,-1,0,0,0,0,-1,-1,-1,-1,-1,0,0,0,0,0\n";
            } else {
                out << index << ',' << std::setprecision(17) << timestamp
                    << ",too_few_keypoints,-1," << current.mvKeys.size()
                    << ',' << octave0 << ",-1,-1,-1,-1,-1,-1,-1,-1,0,0,-1,-1,-1,-1,-1,0,0,0,0,-1,-1,-1,-1,-1,0,0,0,0,0\n";
            }
            ++index;
            continue;
        }

        if (current.mvKeys.size() <= 100) {
            out << index << ',' << std::setprecision(17) << timestamp
                << ",reset_too_few_keypoints," << reference_index << ',' << current.mvKeys.size()
                << ',' << octave0 << ",-1,-1,-1,-1,-1,-1,-1,-1,0,0,-1,-1,-1,-1,-1,0,0,0,0,-1,-1,-1,-1,-1,0,0,0,0,0\n";
            have_initializer = false;
            initializer.reset();
            std::fill(matches.begin(), matches.end(), -1);
            ++index;
            continue;
        }

        FeatureMatcher matcher(0.9f, true);
        int nmatches = matcher.SearchForInitialization(
            *initial, current, prev_matched, matches, 100, DESC_R2D2);
        std::vector<cv::Point2f> p1, p2;
        std::vector<double> displacements;
        p1.reserve(nmatches); p2.reserve(nmatches); displacements.reserve(nmatches);
        for (size_t i = 0; i < matches.size(); ++i) {
            if (matches[i] < 0) continue;
            const auto& a = initial->mvKeysUn[i].pt;
            const auto& b = current.mvKeysUn[matches[i]].pt;
            p1.push_back(a); p2.push_back(b);
            double dx = static_cast<double>(b.x - a.x);
            double dy = static_cast<double>(b.y - a.y);
            displacements.push_back(std::sqrt(dx * dx + dy * dy));
        }

        int h_in = -1, f_in = -1, e_in = -1, pose_in = -1;
        if (p1.size() >= 8) {
            cv::Mat mask_h, mask_f, mask_e, R, t;
            cv::findHomography(p1, p2, cv::RANSAC, 3.0, mask_h, 2000, 0.995);
            cv::findFundamentalMat(p1, p2, cv::FM_RANSAC, 1.0, 0.995, 2000, mask_f);
            cv::Mat E = cv::findEssentialMat(p1, p2, K, cv::RANSAC, 0.995, 1.0, mask_e);
            h_in = mask_h.empty() ? 0 : cv::countNonZero(mask_h);
            f_in = mask_f.empty() ? 0 : cv::countNonZero(mask_f);
            e_in = mask_e.empty() ? 0 : cv::countNonZero(mask_e);
            if (!E.empty()) {
                cv::Mat pose_mask = mask_e.clone();
                pose_in = cv::recoverPose(E, p1, p2, K, R, t, pose_mask);
            }
        }

        bool init_success = false;
        int triangulated = 0;
        float official_sh = -1.0f, official_sf = -1.0f, official_rh = -1.0f;
        int official_h_inliers = -1, official_f_inliers = -1;
        bool official_h_ok = false, official_f_ok = false;
        bool official_h_relaxed = false, official_f_relaxed = false;
        HDiagnostics hdiag;
        std::string event = "geometry_attempt";
        if (nmatches < 100) {
            event = "reset_too_few_matches";
            have_initializer = false;
            initializer.reset();
        } else {
            mat3f Rcw{};
            vec3f tcw{};
            std::vector<vec3f> p3d;
            std::vector<bool> is_triangulated;
            init_success = initializer->Initialize(
                current, matches, Rcw, tcw, p3d, is_triangulated);
            triangulated = static_cast<int>(std::count(
                is_triangulated.begin(), is_triangulated.end(), true));
            std::vector<bool> inliers_h, inliers_f;
            mat3f H{}, F{};
            initializer->FindHomography(inliers_h, official_sh, H);
            initializer->FindFundamental(inliers_f, official_sf, F);
            official_rh = official_sh / (official_sh + official_sf);
            official_h_inliers = static_cast<int>(std::count(inliers_h.begin(), inliers_h.end(), true));
            official_f_inliers = static_cast<int>(std::count(inliers_f.begin(), inliers_f.end(), true));
            mat3f rh{}, rf{}; vec3f th{}, tf{};
            std::vector<vec3f> ph, pf; std::vector<bool> trih, trif;
            official_h_ok = initializer->ReconstructH(inliers_h, H, initializer->K,
                rh, th, ph, trih, 1.0f, 50);
            official_f_ok = initializer->ReconstructF(inliers_f, F, initializer->K,
                rf, tf, pf, trif, 1.0f, 50);
            std::vector<vec3f> phr, pfr; std::vector<bool> trihr, trifr;
            official_h_relaxed = initializer->ReconstructH(inliers_h, H, initializer->K,
                rh, th, phr, trihr, 0.0f, 0);
            official_f_relaxed = initializer->ReconstructF(inliers_f, F, initializer->K,
                rf, tf, pfr, trifr, 0.0f, 0);
            hdiag = diagnose_h(*initializer, inliers_h, H);
            if (init_success) event = "initializer_success";
            else event = "initializer_geometry_reject";
        }

        out << index << ',' << std::setprecision(17) << timestamp << ',' << event << ','
            << reference_index << ',' << current.mvKeys.size() << ',' << octave0 << ','
            << nmatches << ',' << quantile(displacements, 0.1) << ','
            << quantile(displacements, 0.5) << ',' << quantile(displacements, 0.9) << ','
            << h_in << ',' << f_in << ',' << e_in << ',' << pose_in << ','
            << (init_success ? 1 : 0) << ',' << triangulated << ',' << official_sh << ','
            << official_sf << ',' << official_rh << ',' << official_h_inliers << ','
            << official_f_inliers << ',' << (official_h_ok ? 1 : 0) << ','
            << (official_f_ok ? 1 : 0) << ',' << (official_h_relaxed ? 1 : 0) << ','
            << (official_f_relaxed ? 1 : 0) << ',' << hdiag.best_good << ','
            << hdiag.second_good << ',' << hdiag.best_parallax << ',' << hdiag.d1_d2 << ','
            << hdiag.d2_d3 << ',' << (hdiag.svd_ok ? 1 : 0) << ','
            << (hdiag.ambiguity_ok ? 1 : 0) << ',' << (hdiag.parallax_ok ? 1 : 0) << ','
            << (hdiag.min_good_ok ? 1 : 0) << ',' << (hdiag.fraction_ok ? 1 : 0) << '\n';
        if (init_success) break;
        ++index;
    }
    return 0;
}

