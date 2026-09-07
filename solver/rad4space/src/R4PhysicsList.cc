//
// R4PhysicsList.cc
//   Replaceable reference physics list (G4PhysListFactory), modeled on
//   Gorad's GRPhysicsList.
//
//   REGISTRATION
//     This object is registered with the run manager directly in rad4space.cc
//     (main), together with the detector construction and the action
//     initialization.  The /rad4space/physics/* UI options only mutate plain
//     members; the reference list itself is generated lazily by GeneratePL()
//     on first use inside ConstructParticle()/ConstructProcess()/SetCuts(),
//     which Geant4 calls when the run manager initializes -- i.e. well after
//     the macro commands in run.mac have been processed.
//     The physics options (SetPL/AddHP/AddRDM/SetGlobalCut/SetMaxStep) must
//     therefore be issued in the PreInit state, BEFORE /run/initialize
//     (as done in run.mac).  There is no /rad4space/initialize command:
//     initialization is the standard Geant4 /run/initialize.
//

#include "R4PhysicsList.hh"

#include "G4PhysListFactory.hh"
#include "G4GenericMessenger.hh"
#include "G4RadioactiveDecayPhysics.hh"
#include "G4StepLimiterPhysics.hh"
#include "G4UserLimits.hh"
#include "G4LogicalVolumeStore.hh"
#include "G4Threading.hh"

R4PhysicsList::R4PhysicsList()
{
  messenger = new G4GenericMessenger(this, "/rad4space/physics/",
                                     "rad4space physics commands");

  auto& plCmd = messenger->DeclareProperty(
      "SetPL", fPLName,
      "Reference physics list name (e.g. FTFP_BERT, QGSP_BIC, Shielding, "
      "Shielding_EMY, ...). Full name must be a valid G4PhysListFactory "
      "reference list, otherwise initialization aborts."
      "reference: Guide For Physics Lists Release 11.4");
  plCmd.SetStates(G4State_PreInit);
  plCmd.SetToBeBroadcasted(false);

  auto& hpCmd = messenger->DeclareProperty(
      "AddHP", fAddHP,
      "Append the _HP (high-precision neutron) variant "
      "(no effect with Shielding)");
  hpCmd.SetStates(G4State_PreInit);
  hpCmd.SetToBeBroadcasted(false);

  auto& rdmCmd = messenger->DeclareProperty(
      "AddRDM", fAddRDM,
      "Register G4RadioactiveDecayPhysics (no effect with Shielding)");
  rdmCmd.SetStates(G4State_PreInit);
  rdmCmd.SetToBeBroadcasted(false);

  auto& cutCmd = messenger->DeclarePropertyWithUnit(
      "SetGlobalCut", "mm", fGlobalCut,
      "Global production cut for gamma, e-, e+ and proton");
  cutCmd.SetToBeBroadcasted(false);

  auto& msCmd = messenger->DeclarePropertyWithUnit(
      "SetMaxStep", "mm", fMaxStep,
      "Maximum step length for all particles via G4UserLimits (0 = off)");
  msCmd.SetStates(G4State_PreInit);
  msCmd.SetToBeBroadcasted(false);
}

R4PhysicsList::~R4PhysicsList()
{
  delete messenger;
  delete factory;
  delete physList;
  delete fUserLimits;
}

void R4PhysicsList::ConstructParticle()
{
  if (!physList) GeneratePL();
  physList->ConstructParticle();
}

void R4PhysicsList::ConstructProcess()
{
  if (!physList) GeneratePL();
  physList->ConstructProcess();

  // Apply a maximum step length to every logical volume (
  // implemented with G4UserLimits). Set once on the master thread only.
  if (fMaxStep > 0.0 && !fLimitsApplied && G4Threading::IsMasterThread())
  {
    fUserLimits = new G4UserLimits(fMaxStep);
    auto* store = G4LogicalVolumeStore::GetInstance();
    for (auto* lv : *store) lv->SetUserLimits(fUserLimits);
    fLimitsApplied = true;
    G4cout << "rad4space : max step = " << fMaxStep/mm
           << " mm applied to all volumes (G4UserLimits)" << G4endl;
  }
}

void R4PhysicsList::SetCuts()
{
  if (!physList) GeneratePL();
  physList->SetCutValue(fGlobalCut, "gamma");
  physList->SetCutValue(fGlobalCut, "e-");
  physList->SetCutValue(fGlobalCut, "e+");
  physList->SetCutValue(fGlobalCut, "proton");
}

void R4PhysicsList::GeneratePL()
{
  if (physList) return;

  G4String plname = fPLName;
  if (fAddHP && fPLName != "Shielding") plname += "_HP";

  factory = new G4PhysListFactory();
  if (!factory->IsReferencePhysList(plname))
  {
    G4ExceptionDescription ed;
    ed << "Physics list <" << plname << "> is not a valid reference physics "
          "list. Use /rad4space/physics/SetPL with a G4PhysListFactory name "
          "(e.g. FTFP_BERT, QGSP_BIC, Shielding, FTFP_BERT_EMY, ...) and make "
          "sure it is issued before /run/initialize.";
    G4Exception("R4PhysicsList::GeneratePL()", "R4PHYS001", FatalException, ed);
  }
  physList = factory->GetReferencePhysList(plname);
  G4cout << "rad4space : using reference physics list <" << plname << ">"
         << G4endl;

  // The G4UserLimits max-step set in ConstructProcess() is only honoured if a
  // G4StepLimiter process is actually attached to the particles (Geant4 Book
  // for Application Developers, sec. 5.7.2). Register the builder when a
  // global step limit is requested; otherwise leave the list untouched.
  if (fMaxStep > 0.0)
  {
    physList->RegisterPhysics(new G4StepLimiterPhysics());
    G4cout << "rad4space : G4StepLimiterPhysics registered (max step = "
           << fMaxStep/mm << " mm)" << G4endl;
  }

  if (fAddRDM && fPLName != "Shielding")
  {
    physList->RegisterPhysics(new G4RadioactiveDecayPhysics());
    G4cout << "rad4space : G4RadioactiveDecayPhysics registered" << G4endl;
  }
}
