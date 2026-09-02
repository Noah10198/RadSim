//
// R4ActionInitialization.hh
//   Registers user actions.
//
//   The native 1-D histogram filler (G4TScoreHistFiller<G4AnalysisManager>)
//   is instantiated in the R4RunAction constructor, as recommended in
//   "Geant4 Book For Application Developers", sec. 4.9.8 (Filling 1-D
//   histogram). G4VScoreHistFiller::Instance() provides worker clones.
//

#ifndef R4ActionInitialization_h
#define R4ActionInitialization_h 1

#include "G4VUserActionInitialization.hh"
#include "globals.hh"

class R4ActionInitialization : public G4VUserActionInitialization
{
  public:
    R4ActionInitialization();
    ~R4ActionInitialization() override;

    void BuildForMaster() const override;
    void Build() const override;
};

#endif
