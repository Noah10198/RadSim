//
// R4ActionInitialization.cc
//   Registers user actions.
//

#include "R4ActionInitialization.hh"

#include "R4RunAction.hh"
#include "R4PrimaryGeneratorAction.hh"
#include "R4SteppingAction.hh"

R4ActionInitialization::R4ActionInitialization() = default;

R4ActionInitialization::~R4ActionInitialization() = default;

void R4ActionInitialization::BuildForMaster() const
{
  SetUserAction(new R4RunAction());
}

void R4ActionInitialization::Build() const
{
  auto* runAction = new R4RunAction();
  SetUserAction(runAction);
  SetUserAction(new R4PrimaryGeneratorAction());
  // TEMPORARY debug prototype: print trajectory points to the terminal.
  // Remove together with R4SteppingAction.{hh,cc} once the real scheme exists.
  SetUserAction(new R4SteppingAction(runAction));
}
