//
// R4RunAction.hh
//   Minimal analysis-file handling with native G4AnalysisManager.
//   Histograms are defined via UI commands (/analysis/h1/create)
//   and filled by G4TScoreHistFiller (/score/fill1D).
//

#ifndef R4RunAction_h
#define R4RunAction_h 1

#include "G4UserRunAction.hh"
#include "globals.hh"

class G4GenericMessenger;

class R4RunAction : public G4UserRunAction
{
  public:
    R4RunAction();
    ~R4RunAction() override;

    void BeginOfRunAction(const G4Run*) override;
    void EndOfRunAction(const G4Run*) override;

  private:
    G4GenericMessenger* messenger = nullptr;
    G4String fFileName = "rad4space";
    G4bool fFileOpen = false;
};

#endif
