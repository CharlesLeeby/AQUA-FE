// Project-side headless entry for the frozen HFNet-SLAM c354 build.
//
// The official mono-inertial EuRoC entrypoint is included below verbatim from
// the clean official checkout.  The preprocessor renames only the System type
// used by that translation unit.  The derived adapter forwards every public
// operation unchanged and changes exactly one constructor argument:
// bUseViewer=false.  No tracker, extractor, initializer, optimizer, loop-
// closing, dataset-reader, pacing, shutdown, or trajectory-save code is
// duplicated or changed here.

#include <System.h>

namespace ORB_SLAM3 {

class HeadlessSystem final : public System {
public:
    HeadlessSystem(const std::string &settings_file,
                   const eSensor sensor,
                   const bool /* official_entry_requested_viewer */ = true,
                   const int init_frame = 0)
        : System(settings_file, sensor, false, init_frame) {}
};

}  // namespace ORB_SLAM3

#define System HeadlessSystem
#include "/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1/Examples/Monocular-Inertial/mono_inertial_euroc.cc"
#undef System
