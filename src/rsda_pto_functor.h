#pragma once
// =============================================================================
// rsda_pto_functor.h
// Rotational analog of SEA-Stack's PTOForceFunctor for ChLinkRSDA.
//
// ChLinkRSDA (Rotational Spring-Damper-Actuator) is Chrono 10's rotational
// counterpart to ChLinkTSDA.  Its TorqueFunctor callback receives:
//   time  — current simulation time [s]
//   angle — relative rotation angle [rad]   (maps to IPTOModel::displacement)
//   vel   — relative angular velocity [rad/s] (maps to IPTOModel::velocity)
//
// Typical wiring (Y-axis hinge):
//   auto rsda = chrono_types::make_shared<ChLinkRSDA>();
//   ChQuaternion<> rot = QuatFromAngleX(CH_PI / 2.0);  // Z→Y
//   rsda->Initialize(base_body, flap_body, false,
//                    ChFramed(hinge_pos, rot), ChFramed(hinge_pos, rot));
//   rsda->RegisterTorqueFunctor(
//       std::make_shared<vgoswec::RsdaPtoFunctor>(controller));
//   system.AddLink(rsda);
// =============================================================================
#ifndef VGOSWEC_RSDA_PTO_FUNCTOR_H
#define VGOSWEC_RSDA_PTO_FUNCTOR_H

#include <memory>
#include <chrono/physics/ChLinkRSDA.h>
#include <seastack/pto/pto_model.h>

namespace vgoswec {

/// ChLinkRSDA::TorqueFunctor that delegates to an IPTOModel.
///
/// The angle reported by ChLinkRSDA is the relative rotation about the
/// joint's Z axis (which we orient to be world Y by setting revoluteRot =
/// QuatFromAngleX(CH_PI/2)).  This angle equals the flap deviation θ from
/// its equilibrium orientation (assuming the joint was initialized at rest).
class RsdaPtoFunctor : public ::chrono::ChLinkRSDA::TorqueFunctor {
 public:
    /// @param model  Shared ownership of the PTO model.  Must not be null.
    explicit RsdaPtoFunctor(std::shared_ptr<seastack::pto::IPTOModel> model);

    /// Called by Chrono at each force-assembly sub-step.
    double evaluate(double time,
                    double angle,
                    double vel,
                    const ::chrono::ChLinkRSDA& link) override;

 private:
    std::shared_ptr<seastack::pto::IPTOModel> model_;
};

}  // namespace vgoswec

#endif  // VGOSWEC_RSDA_PTO_FUNCTOR_H
