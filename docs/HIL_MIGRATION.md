# HIL Migration Guide

How to replace a simulation controller with a hardware-in-the-loop (HIL) or
ROS 2 implementation without modifying the simulation.

## Interface contract

All four PTO controllers implement:
```cpp
namespace seastack::pto {
class IPTOModel {
 public:
  virtual double ComputeForce(double displacement,   // flap angle θ [rad]
                               double velocity,        // θ̇ [rad/s]
                               double time) = 0;       // sim time [s]
};
}  // namespace seastack::pto
```

`RsdaPtoFunctor` calls `ComputeForce` at every Chrono sub-step during
`DoStepDynamics`. The return value is applied as torque about the hinge Y-axis.

## Creating a ROS 2 HIL controller

```cpp
// ros_pto_model.h
#include <seastack/pto/pto_model.h>
#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/float64.hpp>

class RosPTOModel : public seastack::pto::IPTOModel {
 public:
  RosPTOModel(rclcpp::Node::SharedPtr node)
    : node_(node) {
    torque_sub_ = node->create_subscription<std_msgs::msg::Float64>(
        "/vgoswec/pto_torque_cmd", 10,
        [this](const std_msgs::msg::Float64::SharedPtr msg) {
            std::lock_guard<std::mutex> lk(mu_);
            latest_torque_ = msg->data;
        });
    state_pub_ = node->create_publisher<std_msgs::msg::Float64>(
        "/vgoswec/flap_angle", 10);
  }

  double ComputeForce(double disp, double vel, double t) override {
    // Publish current state to HIL hardware
    std_msgs::msg::Float64 msg;
    msg.data = disp;
    state_pub_->publish(msg);
    // Return latest torque command from hardware
    std::lock_guard<std::mutex> lk(mu_);
    return latest_torque_;
  }

 private:
  rclcpp::Node::SharedPtr node_;
  rclcpp::Subscription<std_msgs::msg::Float64>::SharedPtr torque_sub_;
  rclcpp::Publisher<std_msgs::msg::Float64>::SharedPtr state_pub_;
  std::mutex mu_;
  double latest_torque_{0.0};
};
```

## Dropping it in

```cpp
// In demo_vgoswec.cpp or a ROS 2 node
auto ros_controller = std::make_shared<RosPTOModel>(node);
auto rsda = chrono_types::make_shared<ChLinkRSDA>();
rsda->Initialize(base_body, flap_body, false, hinge_frame, hinge_frame);
rsda->RegisterTorqueFunctor(
    std::make_shared<vgoswec::RsdaPtoFunctor>(ros_controller));
system.AddLink(rsda);
```

No other simulation code changes required. The controller selection in
`--controller` CLI arg can add `ros` as a new type.

## Latency considerations

- `ComputeForce` is called at each Chrono sub-step (dt ≈ 0.005 s).
- For real-time HIL, the ROS callback must deliver torque within one timestep.
- Network latency > dt will cause stale torque (benign for slow systems, may
  destabilize resonant WECs near ω₀).
- Recommendation: run the ROS 2 node on the same machine as the simulation
  using intra-process communication, or use a dedicated real-time executor.

## ExcitationForceProvider in HIL mode

`ExcitationForceProvider::GetLatestExcitationTorque()` can be published
over ROS to provide feedforward data to hardware:
```cpp
// In time loop:
exc_msg.data = exc_provider->GetLatestExcitationTorque();
exc_pub->publish(exc_msg);
```
