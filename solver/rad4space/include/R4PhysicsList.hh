//
// R4PhysicsList.hh
//   Replaceable reference physics list built on G4PhysListFactory
//   (like Gorad, but minimal).
//

#ifndef R4PhysicsList_h
#define R4PhysicsList_h 1

#include "G4VModularPhysicsList.hh"
#include "globals.hh"
#include "G4SystemOfUnits.hh"

class G4PhysListFactory;
class G4GenericMessenger;
class G4UserLimits;

class R4PhysicsList : public G4VModularPhysicsList
{
  public:
    R4PhysicsList();
    ~R4PhysicsList() override;

    void ConstructParticle() override;
    void ConstructProcess() override;
    void SetCuts() override;

  private:
    void GeneratePL();

    G4String fPLName = "FTFP_BERT";   // reference physics list
    G4bool fAddHP = false;            // append _HP variant
    G4bool fAddRDM = false;           // register G4RadioactiveDecayPhysics
    G4double fGlobalCut = 0.7*mm;     // production cut for gamma/e-/e+/proton
    G4double fMaxStep = 0.0;          // max step via G4UserLimits (0 = off)

    G4PhysListFactory* factory = nullptr;
    G4VModularPhysicsList* physList = nullptr;
    G4GenericMessenger* messenger = nullptr;
    G4UserLimits* fUserLimits = nullptr;
    G4bool fLimitsApplied = false;
};

#endif
