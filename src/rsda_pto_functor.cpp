// rsda_pto_functor.cpp
#include "rsda_pto_functor.h"

namespace vgoswec {

RsdaPtoFunctor::RsdaPtoFunctor(std::shared_ptr<seastack::pto::IPTOModel> model)
    : model_(std::move(model)) {}

double RsdaPtoFunctor::evaluate(double time, double /*rest_angle*/, double angle, double vel,
                                const ::chrono::ChLinkRSDA& /*link*/) {
    // angle -> flap deviation theta [rad] (displacement); vel -> theta_dot [rad/s].
    // rest_angle is unused: the controllers reference theta from the initialized-at-rest
    // configuration (rest_angle = 0), matching theta_ref = 0 in the exc_ff_pid controller.
    return model_->ComputeForce(angle, vel, time);
}

}  // namespace vgoswec
