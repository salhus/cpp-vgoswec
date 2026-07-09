#pragma once
// =============================================================================
// excitation_force_provider.h
// Cache-and-broadcast helper for the wave excitation torque on the flap.
//
// Usage pattern (main time loop):
//   std::vector<seastack::hydro::ComponentForceRecord> per_comp;
//   hydro_forces.Evaluate(state, time, &per_comp);
//   exc_provider.Update(per_comp);
//   // ... ExcitationVelocityController reads GetLatestExcitationTorque()
//
// DOF convention (BEMIO / WEC-Sim):
//   0 = surge (Fx), 1 = sway (Fy), 2 = heave (Fz),
//   3 = roll (Mx), 4 = pitch (My), 5 = yaw (Mz)
//
// For the VGOSWEC bottom-hinged flap rotating about Y:
//   Use dof_index = 4 (pitch).
//   Excitation torque is ComponentForceRecord.forces[flap_index].moment.y()
// =============================================================================
#ifndef VGOSWEC_EXCITATION_FORCE_PROVIDER_H
#define VGOSWEC_EXCITATION_FORCE_PROVIDER_H

#include <vector>
#include <seastack/core/force_component.h>

namespace vgoswec {

class ExcitationForceProvider {
 public:
    /// @param flap_body_index  Index of flap in the SEA-Stack bodies vector (0)
    /// @param dof_index        DOF for excitation torque: 4 = pitch about Y
    ExcitationForceProvider(int flap_body_index, int dof_index);

    /// Extract and cache the excitation torque from a per-component snapshot.
    /// Call this after HydroForces::Evaluate fills per_component.
    void Update(const std::vector<seastack::hydro::ComponentForceRecord>& per_component,
                double time = -1.0);

    /// Set cached excitation torque directly (e.g. from analytic wave field).
    void UpdateDirect(double torque_nm, double time);

    double GetLatestExcitationTorque() const { return latest_exc_torque_; }
    double GetLatestUpdateTime() const { return latest_time_; }

 private:
    int flap_body_index_;   ///< 0 for VGOSWEC (flap is first in bodies vector)
    int dof_index_;         ///< 4 = pitch DOF
    double latest_exc_torque_{0.0};
    double latest_time_{-1.0};
};

}  // namespace vgoswec

#endif  // VGOSWEC_EXCITATION_FORCE_PROVIDER_H
