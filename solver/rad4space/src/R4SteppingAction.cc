//
// R4SteppingAction.cc
//   See R4SteppingAction.hh
//

#include "R4SteppingAction.hh"

#include "R4RunAction.hh"

#include "G4Event.hh"
#include "G4EventManager.hh"
#include "G4ios.hh"
#include "G4ParticleDefinition.hh"
#include "G4Step.hh"
#include "G4StepPoint.hh"
#include "G4Threading.hh"
#include "G4ThreeVector.hh"
#include "G4Track.hh"

R4SteppingAction::R4SteppingAction(R4RunAction* runAction)
  : fRunAction(runAction)
{}

void R4SteppingAction::UserSteppingAction(const G4Step* step)
{
  // Elect a single recorder thread for this run: the first worker that steps
  // wins.  Numbering differs between tasking (workers 0..N-1) and classic MT
  // (master 0, workers 1..N), so a fixed id would be wrong for one of them.
  if (!fIsRecorder)
  {
    if (!fRunAction->ClaimRecorder()) return;   // another thread is recorder
    fIsRecorder = true;
    // One line per run: tells you WHICH worker's events landed in Traj.csv.
    G4cout << "[Traj] recorder elected on thread "
           << G4Threading::G4GetThreadId() << G4endl;
  }

  // Caps reached (event / point): stop calling the run action entirely.
  if (fRunAction->TrajStopped()) return;

  const G4Track* track = step->GetTrack();
  const G4int stepNumber = track->GetCurrentStepNumber();

  auto emitPoint = [&](G4int s, const G4StepPoint* pt)
  {
    const G4Event* event =
      G4EventManager::GetEventManager()->GetConstCurrentEvent();
    const G4ParticleDefinition* def = track->GetDefinition();
    const G4ThreeVector& pos = pt->GetPosition();

    fRunAction->RecordTrajPoint(
        event->GetEventID(), track->GetTrackID(), track->GetParentID(),
        def->GetPDGEncoding(), s, pos.x(), pos.y(), pos.z());
  };

  // Origin / vertex of the track (only the first step carries it).
  if (stepNumber == 1) emitPoint(0, step->GetPreStepPoint());

  // End point of every segment.
  emitPoint(stepNumber, step->GetPostStepPoint());
}
