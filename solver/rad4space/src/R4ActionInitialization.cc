//
// R4ActionInitialization.cc
//   Registers user actions.
//

#include "R4ActionInitialization.hh"

#include "R4RunAction.hh"
#include "R4PrimaryGeneratorAction.hh"

R4ActionInitialization::R4ActionInitialization() = default;

R4ActionInitialization::~R4ActionInitialization() = default;

void R4ActionInitialization::BuildForMaster() const
{
  SetUserAction(new R4RunAction());
}

void R4ActionInitialization::Build() const
{
  SetUserAction(new R4RunAction());
  SetUserAction(new R4PrimaryGeneratorAction());
}
