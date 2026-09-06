//
// R4Initialization.cc
//   Gorad-style late initialization of rad4space.
//
//   The detector, physics list and action initialization objects are created
//   here (so their messengers are available from the very beginning) but are
//   handed over to the G4RunManager only when the user executes
//   /rad4space/initialize in the macro -- i.e. after all PreInit physics and
//   geometry options have been set.
//

#include "R4Initialization.hh"

#include "R4DetectorConstruction.hh"
#include "R4PhysicsList.hh"
#include "R4ActionInitialization.hh"

#include "G4GenericMessenger.hh"
#include "G4RunManager.hh"

R4Initialization::R4Initialization()
{
  messenger = new G4GenericMessenger(this, "/rad4space/",
                                     "rad4space commands");
  auto& initCmd = messenger->DeclareMethod(
      "initialize", &R4Initialization::Initialize,
      "Register detector/physics/user-actions with the run manager and "
      "initialize the run manager");
  initCmd.SetToBeBroadcasted(false);
  initCmd.SetStates(G4State_PreInit);

  // Create (but do not register) the mandatory initialization objects.
  // Their messengers can then be steered by macro commands while the
  // run manager is still in the PreInit state.
  detector = new R4DetectorConstruction();
  physics = new R4PhysicsList();
  action = new R4ActionInitialization();
}

R4Initialization::~R4Initialization()
{
  delete messenger;

  // After Initialize() the run manager owns the registered objects and will
  // delete them when it is destroyed.  If Initialize() was never called we
  // still own them here and must clean them up ourselves.
  if (!fInitialized)
  {
    delete detector;
    delete physics;
    delete action;
  }
}

void R4Initialization::Initialize()
{
  auto runManager = G4RunManager::GetRunManager();
  runManager->SetUserInitialization(detector);
  runManager->SetUserInitialization(physics);
  runManager->SetUserInitialization(action);
  G4cout << "rad4space : registering user initializations and initializing"
         << G4endl;
  runManager->Initialize();
  fInitialized = true;
}
