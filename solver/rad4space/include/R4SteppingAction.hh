//
// R4SteppingAction.hh
//   Feeds trajectory points to the R4RunAction, which accumulates them in a
//   shared store and writes Traj.csv once from the master EndOfRunAction.
//
//   Point sequence recorded per track:
//     - step #1 pre-step point  (step=0) -> origin / vertex of the track
//     - every step post-step point       -> each segment end
//
//   The single recorder is elected atomically: the first worker thread that
//   steps wins (ClaimRecorder()).  This avoids hard-coding a thread number,
//   which differs between tasking (workers 0..N-1) and classic MT
//   (master 0, workers 1..N).  Limits are hard-coded in R4RunAction.cc.
//

#ifndef R4SteppingAction_h
#define R4SteppingAction_h 1

#include "G4UserSteppingAction.hh"
#include "globals.hh"

class G4Step;
class R4RunAction;

class R4SteppingAction : public G4UserSteppingAction
{
  public:
    explicit R4SteppingAction(R4RunAction* runAction);
    ~R4SteppingAction() override = default;

    void UserSteppingAction(const G4Step*) override;

  private:
    R4RunAction* fRunAction = nullptr;
    G4bool fIsRecorder = false;   // true once this thread won ClaimRecorder()
};

#endif
