// Standalone installed ROS time semantics check; never runs VINS or estimation.
#include <ros/time.h>
#include <iostream>
#include <cstdint>
int main() {
    std::uint64_t ns;
    while (std::cin >> ns) {
        ros::Time original;
        original.fromNSec(ns);
        const ros::Time published(original.toSec());
        std::cout << published.toNSec() << '\n';
    }
}
