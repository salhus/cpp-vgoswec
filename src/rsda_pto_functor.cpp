// rsda_pto_functor.cpp
#include "rsda_pto_functor.h"

namespace vgoswec {

RsdaPtoFunctor::RsdaPtoFunctor(std::shared_ptr<seastack::pto::IPTOModel> model)
    : model_(std::move(model)) {}

double RsdaPtoFunctor::evaluate(double time, double angle, double vel,
                                const ::chrono::ChLinkRSDA& /*link*/) {
    return model_->ComputeForce(angle, vel, time);
}

}  // namespace vgoswec
