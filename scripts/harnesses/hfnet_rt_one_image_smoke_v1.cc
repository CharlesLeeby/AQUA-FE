// Project-side, single-image smoke harness for the published HFNet-SLAM code.
//
// This file intentionally contains no feature implementation.  It links to
// the author-built libHFNet_SLAM.so, asks the official InitAllModels routine
// for the four TensorRT models, and invokes the official four-level
// HFextractor exactly once.  The surrounding Python runner freezes the only
// accepted image/model/source identities and captures the official logs.

#include <cerrno>
#include <cmath>
#include <cstring>
#include <fcntl.h>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>

#include <opencv2/core.hpp>
#include <opencv2/imgcodecs.hpp>

#include "Extractors/BaseModel.h"
#include "Extractors/HFNetRTModel.h"
#include "Extractors/HFextractor.h"

namespace {

constexpr const char* kRawSchema =
    "aqua-fe-published-hfnet-rt-one-image-smoke-raw-v1";
constexpr int kExpectedWidth = 968;
constexpr int kExpectedHeight = 608;
constexpr int kLevels = 4;
constexpr int kFeatures = 675;
constexpr float kScaleFactor = 1.2F;
constexpr float kThreshold = 0.01F;

std::string JsonEscape(const std::string& value) {
    std::ostringstream escaped;
    for (const unsigned char character : value) {
        switch (character) {
            case '"': escaped << "\\\""; break;
            case '\\': escaped << "\\\\"; break;
            case '\b': escaped << "\\b"; break;
            case '\f': escaped << "\\f"; break;
            case '\n': escaped << "\\n"; break;
            case '\r': escaped << "\\r"; break;
            case '\t': escaped << "\\t"; break;
            default:
                if (character < 0x20U) {
                    escaped << "\\u" << std::hex << std::setw(4)
                            << std::setfill('0')
                            << static_cast<unsigned int>(character)
                            << std::dec << std::setfill(' ');
                } else {
                    escaped << character;
                }
        }
    }
    return escaped.str();
}

bool WriteExclusive(const std::string& path, const std::string& payload) {
    const int descriptor =
        ::open(path.c_str(), O_WRONLY | O_CREAT | O_EXCL, S_IRUSR | S_IWUSR);
    if (descriptor < 0) {
        std::cerr << "HARNESS_CONTRACT_ERROR: cannot create result file "
                  << path << ": " << std::strerror(errno) << std::endl;
        return false;
    }

    const char* cursor = payload.data();
    std::size_t remaining = payload.size();
    while (remaining > 0U) {
        const ssize_t written = ::write(descriptor, cursor, remaining);
        if (written < 0) {
            if (errno == EINTR) continue;
            std::cerr << "HARNESS_CONTRACT_ERROR: cannot write result file: "
                      << std::strerror(errno) << std::endl;
            ::close(descriptor);
            return false;
        }
        if (written == 0) {
            std::cerr << "HARNESS_CONTRACT_ERROR: zero-byte result write"
                      << std::endl;
            ::close(descriptor);
            return false;
        }
        cursor += written;
        remaining -= static_cast<std::size_t>(written);
    }
    if (::fsync(descriptor) != 0) {
        std::cerr << "HARNESS_CONTRACT_ERROR: cannot fsync result file: "
                  << std::strerror(errno) << std::endl;
        ::close(descriptor);
        return false;
    }
    if (::close(descriptor) != 0) {
        std::cerr << "HARNESS_CONTRACT_ERROR: cannot close result file: "
                  << std::strerror(errno) << std::endl;
        return false;
    }
    return true;
}

int WriteFailure(const std::string& result_path, const std::string& error,
                 int return_code) {
    std::ostringstream result;
    result << "{\"error\":\"" << JsonEscape(error)
           << "\",\"ok\":false,\"schema_version\":\"" << kRawSchema
           << "\"}\n";
    if (!WriteExclusive(result_path, result.str())) return 2;
    return return_code;
}

bool IsFiniteMatrix(const cv::Mat& matrix) {
    if (matrix.type() != CV_32F) return false;
    for (int row = 0; row < matrix.rows; ++row) {
        const float* values = matrix.ptr<float>(row);
        for (int column = 0; column < matrix.cols; ++column) {
            if (!std::isfinite(values[column])) return false;
        }
    }
    return true;
}

bool AreFiniteKeypoints(const std::vector<cv::KeyPoint>& keypoints,
                        const cv::Size& size) {
    for (const cv::KeyPoint& keypoint : keypoints) {
        if (!std::isfinite(keypoint.pt.x) ||
            !std::isfinite(keypoint.pt.y) ||
            !std::isfinite(keypoint.response)) {
            return false;
        }
        if (keypoint.pt.x < 0.0F || keypoint.pt.x >= size.width ||
            keypoint.pt.y < 0.0F || keypoint.pt.y >= size.height) {
            return false;
        }
        if (keypoint.octave < 0 || keypoint.octave >= kLevels) return false;
    }
    return true;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 4) {
        std::cerr << "Usage: hfnet_rt_one_image_smoke_v1 IMAGE MODEL_DIR "
                     "RAW_RESULT_JSON"
                  << std::endl;
        return 2;
    }

    const std::string image_path(argv[1]);
    const std::string model_directory(argv[2]);
    const std::string result_path(argv[3]);

    const cv::Mat image = cv::imread(image_path, cv::IMREAD_GRAYSCALE);
    if (image.empty()) {
        return WriteFailure(result_path, "fixed_input_image_unreadable", 2);
    }
    if (image.type() != CV_8UC1 || image.cols != kExpectedWidth ||
        image.rows != kExpectedHeight) {
        return WriteFailure(result_path, "fixed_input_image_contract_mismatch", 2);
    }

    try {
        // Official high-level constructor: creates one kImageToLocalAndGlobal
        // model at level 0 and three kImageToLocal models at levels 1--3.
        ORB_SLAM3::InitAllModels(model_directory, ORB_SLAM3::kHFNetRTModel,
                                image.size(), kLevels, kScaleFactor);
        const std::vector<ORB_SLAM3::BaseModel*> models =
            ORB_SLAM3::GetModelVec();
        if (models.size() != static_cast<std::size_t>(kLevels)) {
            return WriteFailure(result_path, "official_model_count_not_four", 1);
        }
        for (ORB_SLAM3::BaseModel* model : models) {
            if (model == nullptr || !model->IsValid() ||
                dynamic_cast<ORB_SLAM3::HFNetRTModel*>(model) == nullptr) {
                return WriteFailure(result_path,
                                    "official_hfnet_rt_model_invalid", 1);
            }
        }

        ORB_SLAM3::HFextractor extractor(
            kFeatures, kThreshold, kScaleFactor, kLevels, models);
        std::vector<cv::KeyPoint> keypoints;
        cv::Mat local_descriptors;
        cv::Mat global_descriptor;

        // Exactly one frontend invocation on exactly one frozen image.  The
        // unmodified official extractor dispatches one Detect call per level.
        const int extracted =
            extractor(image, keypoints, local_descriptors, global_descriptor);

        const bool output_contract_ok =
            extracted > 0 &&
            extracted == static_cast<int>(keypoints.size()) &&
            extracted <= kFeatures &&
            local_descriptors.rows == extracted &&
            local_descriptors.cols == 256 &&
            local_descriptors.type() == CV_32F &&
            global_descriptor.rows == 4096 &&
            global_descriptor.cols == 1 &&
            global_descriptor.type() == CV_32F &&
            IsFiniteMatrix(local_descriptors) &&
            IsFiniteMatrix(global_descriptor) &&
            AreFiniteKeypoints(keypoints, image.size());
        if (!output_contract_ok) {
            return WriteFailure(result_path,
                                "official_detect_output_contract_failed", 1);
        }

        std::ostringstream result;
        result << std::setprecision(9)
               << "{\"detect_output\":{\"global_descriptor_cols\":"
               << global_descriptor.cols
               << ",\"global_descriptor_rows\":" << global_descriptor.rows
               << ",\"keypoint_count\":" << keypoints.size()
               << ",\"local_descriptor_cols\":" << local_descriptors.cols
               << ",\"local_descriptor_rows\":" << local_descriptors.rows
               << "},\"fixed_parameters\":{\"features\":" << kFeatures
               << ",\"levels\":" << kLevels
               << ",\"scale_factor\":" << kScaleFactor
               << ",\"threshold\":" << kThreshold
               << "},\"frontend_invocations\":1,"
                  "\"official_level_detect_invocations\":4,\"ok\":true,"
                  "\"schema_version\":\""
               << kRawSchema << "\"}\n";
        if (!WriteExclusive(result_path, result.str())) return 2;
        return 0;
    } catch (const cv::Exception& error) {
        return WriteFailure(result_path,
                            std::string("opencv_exception:") + error.what(), 1);
    } catch (const std::exception& error) {
        return WriteFailure(result_path,
                            std::string("std_exception:") + error.what(), 1);
    } catch (...) {
        return WriteFailure(result_path, "unknown_exception", 1);
    }
}
