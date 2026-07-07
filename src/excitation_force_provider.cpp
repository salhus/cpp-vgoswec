// excitation_force_provider.cpp
#include "excitation_force_provider.h"

namespace vgoswec {

ExcitationForceProvider::ExcitationForceProvider(int flap_body_index, int dof_index)
    : flap_body_index_(flap_body_index), dof_index_(dof_index) {}

void ExcitationForceProvider::Update(
    const std::vector<seastack::hydro::ComponentForceRecord>& per_component,
    double time) {
    // Scan per_component for the kExcitation record and extract pitch torque.
    // BodyForces is a std::vector<GeneralizedForce>; each element has .moment (Vec3).
    // Pitch about Y = moment.y() = DOF index 4.
    for (const auto& rec : per_component) {
        if (rec.type == seastack::hydro::HydroComponentType::kExcitation) {
            if (flap_body_index_ < static_cast<int>(rec.forces.size())) {
                // DOF 4 = pitch about Y: use moment.y()
                latest_exc_torque_ = rec.forces[flap_body_index_].moment.y();
            }
            break;
        }
    }
    if (time >= 0.0) latest_time_ = time;
}

void ExcitationForceProvider::UpdateDirect(double torque_nm, double time) {
    latest_exc_torque_ = torque_nm;
    latest_time_ = time;
}

}  // namespace vgoswec
