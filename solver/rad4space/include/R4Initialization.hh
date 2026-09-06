//
// R4Initialization.hh
//   Holds the detector / physics / user-action objects and defers their
//   registration to the G4RunManager until the /rad4space/initialize UI
//   command is issued (Gorad-style GRInitialization).
//
//   Rationale:
//     Once a physics list is registered with the run manager, Geant4 may
//     touch it (lazy ConstructParticle/ConstructProcess) before any macro
//     command is processed.  If the physics-list object is registered in
//     main(), the reference list generated from the default name is cached
//     before /rad4space/physics/SetPL has a chance to run -- so the chosen
//     physics list never takes effect.  Registering everything from inside
//     the macro (after all PreInit options are set) avoids this pitfall.
//

#ifndef R4Initialization_h
#define R4Initialization_h 1

#include "globals.hh"

class G4GenericMessenger;
class R4DetectorConstruction;
class R4PhysicsList;
class R4ActionInitialization;

class R4Initialization
{
  public:
    R4Initialization();
    ~R4Initialization();

    // UI command target : register all user initializations and call
    // G4RunManager::Initialize() (i.e. /rad4space/initialize).
    void Initialize();

  private:
    G4GenericMessenger* messenger = nullptr;

    R4DetectorConstruction* detector = nullptr;
    R4PhysicsList* physics = nullptr;
    R4ActionInitialization* action = nullptr;

    G4bool fInitialized = false;  // true after Initialize() succeeded
};

#endif
