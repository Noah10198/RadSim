//
// R4RunAction.hh
//   Minimal analysis-file handling with native G4AnalysisManager.
//   Histograms are defined via UI commands (/analysis/h1/create)
//   and filled by G4TScoreHistFiller (/score/fill1D).
//
//   Trajectory dump: one worker thread is elected on the fly (the first one
//   that steps) and calls RecordTrajPoint() for its trajectory points.  The
//   points accumulate in a process-wide store and are written once to
//   Traj.csv from the MASTER EndOfRunAction.  Writing from the master is used
//   because the default tasking run manager runs workers numbered 0..N-1 and
//   merges runs on the master, so a single clean flush point is the master's
//   EndOfRunAction.  Limits are hard-coded in R4RunAction.cc; see README.md.
//

#ifndef R4RunAction_h
#define R4RunAction_h 1

#include "G4UserRunAction.hh"
#include "globals.hh"

class G4GenericMessenger;
class G4Run;

struct R4TrajPoint
{
  G4int    eventID;
  G4int    trackID;
  G4int    parentID;
  G4int    pdg;
  G4int    step;
  G4double x, y, z;   // mm
};

class R4RunAction : public G4UserRunAction
{
  public:
    R4RunAction();
    ~R4RunAction() override;

    void BeginOfRunAction(const G4Run*) override;
    void EndOfRunAction(const G4Run*) override;

    // Called by R4SteppingAction for every trajectory point (only the
    // elected recorder thread reaches this).  Writes the shared store.
    void RecordTrajPoint(G4int eventID, G4int trackID, G4int parentID,
                         G4int pdg, G4int step,
                         G4double x, G4double y, G4double z);

    // Atomically elects the single recorder thread for this run.
    // Returns true exactly once (for the winner).
    G4bool ClaimRecorder();

    // True once the store reached a cap; the stepping action can then stop
    // calling RecordTrajPoint entirely.
    G4bool TrajStopped() const;

  private:
    void WriteTrajFile();

    G4GenericMessenger* messenger = nullptr;   // /rad4space/analysis/
    G4String fFileName = "rad4space";
    G4bool fFileOpen = false;
};

#endif
