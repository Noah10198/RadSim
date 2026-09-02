//
// R4PhysicsList.cc
//   Replaceable reference physics list (G4PhysListFactory), minimal
//   version of Gorad's GRPhysicsList.
//

#include "R4PhysicsList.hh"

#include "G4PhysListFactory.hh"
#include "G4GenericMessenger.hh"
#include "G4RadioactiveDecayPhysics.hh"
#include "G4UserLimits.hh"
#include "G4LogicalVolumeStore.hh"
#include "G4Threading.hh"

R4PhysicsList::R4PhysicsList()
{
  messenger = new G4GenericMessenger(this, "/rad4space/physics/",
                                     "rad4space physics commands");

  auto& plCmd = messenger->DeclareProperty(
      "SetPL", fPLName,
      "Reference physics list name (e.g. FTFP_BERT, QGSP_BIC, Shielding)");
  plCmd.SetStates(G4State_PreInit);
  plCmd.SetToBeBroadcasted(false);

  auto& hpCmd = messenger->DeclareProperty(
      "AddHP", fAddHP,
      "Append the _HP (high-precision neutron) variant");
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

  // Apply a maximum step length to every logical volume (GRAS-style StepMax,
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
    ed << "Physics list <" << plname << "> is not a valid reference physics list.";
    G4Exception("R4PhysicsList::GeneratePL()", "R4PHYS001", FatalException, ed);
  }
  physList = factory->GetReferencePhysList(plname);
  G4cout << "rad4space : using reference physics list <" << plname << ">" << G4endl;

  if (fAddRDM && fPLName != "Shielding")
  {
    physList->RegisterPhysics(new G4RadioactiveDecayPhysics());
    G4cout << "rad4space : G4RadioactiveDecayPhysics registered" << G4endl;
  }
}
