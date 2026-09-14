cmake_minimum_required(VERSION 3.10)
project(aqua_native_loop_baseline_v1)
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_BUILD_TYPE Release)
find_package(catkin REQUIRED COMPONENTS roscpp std_msgs nav_msgs camera_models cv_bridge roslib)
find_package(OpenCV REQUIRED)
find_package(Ceres REQUIRED)
find_package(Eigen3 REQUIRED)
if(NOT NATIVE_SNAPSHOT OR NOT EXISTS "${NATIVE_SNAPSHOT}/pose_graph.cpp")
  message(FATAL_ERROR "Use the identity-checked builder; missing isolated snapshot")
endif()
include_directories(${NATIVE_SNAPSHOT} ${CMAKE_CURRENT_SOURCE_DIR} ${catkin_INCLUDE_DIRS}
                    ${OpenCV_INCLUDE_DIRS} ${CERES_INCLUDE_DIRS} ${EIGEN3_INCLUDE_DIR})
add_executable(aqua_native_loop_replay
  native_loop_replay.cpp
  ${NATIVE_SNAPSHOT}/pose_graph.cpp
  ${NATIVE_SNAPSHOT}/keyframe.cpp
  ${NATIVE_SNAPSHOT}/utility/CameraPoseVisualization.cpp
  ${NATIVE_SNAPSHOT}/ThirdParty/DBoW/BowVector.cpp
  ${NATIVE_SNAPSHOT}/ThirdParty/DBoW/FBrief.cpp
  ${NATIVE_SNAPSHOT}/ThirdParty/DBoW/FeatureVector.cpp
  ${NATIVE_SNAPSHOT}/ThirdParty/DBoW/QueryResults.cpp
  ${NATIVE_SNAPSHOT}/ThirdParty/DBoW/ScoringObject.cpp
  ${NATIVE_SNAPSHOT}/ThirdParty/DUtils/Random.cpp
  ${NATIVE_SNAPSHOT}/ThirdParty/DUtils/Timestamp.cpp
  ${NATIVE_SNAPSHOT}/ThirdParty/DVision/BRIEF.cpp
  ${NATIVE_SNAPSHOT}/ThirdParty/VocabularyBinary.cpp)
target_link_libraries(aqua_native_loop_replay ${catkin_LIBRARIES} ${OpenCV_LIBS} ${CERES_LIBRARIES})
