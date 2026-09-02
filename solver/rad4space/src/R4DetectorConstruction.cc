//
// R4DetectorConstruction.cc
//   GDML import (like Gorad) plus a small geometry utility command.
//

#include "R4DetectorConstruction.hh"

#include "G4GDMLParser.hh"
#include "G4GenericMessenger.hh"
#include "G4LogicalVolume.hh"
#include "G4LogicalVolumeStore.hh"
#include "G4VPhysicalVolume.hh"
#include "G4Material.hh"
#include "G4VSensitiveDetector.hh"

R4DetectorConstruction::R4DetectorConstruction()
{
  parser = new G4GDMLParser();

  messenger = new G4GenericMessenger(this, "/rad4space/gdml/",
                                     "rad4space geometry commands");

  auto& setCmd = messenger->DeclareProperty("SetGDMLFile", fGDMLFile,
                                            "GDML geometry file name");
  setCmd.SetStates(G4State_PreInit);
  setCmd.SetToBeBroadcasted(false);

  auto& listCmd = messenger->DeclareMethod("ListVolumes",
                                           &R4DetectorConstruction::ListVolumes,
                                           "Print the physical volume tree");
  listCmd.SetToBeBroadcasted(false);
}

R4DetectorConstruction::~R4DetectorConstruction()
{
  delete messenger;
  delete parser;
}

G4VPhysicalVolume* R4DetectorConstruction::Construct()
{
  if (!fInitialized) Read();
  return fWorld;
}

void R4DetectorConstruction::ConstructSDandField()
{
  // Scoring is handled natively via G4ScoringManager (/score/ commands),
  // so no sensitive detector is needed here.
}

void R4DetectorConstruction::Read()
{
  G4cout << "rad4space : reading GDML file <" << fGDMLFile << ">" << G4endl;
  parser->Read(fGDMLFile);
  fWorld = parser->GetWorldVolume();
  if (!fWorld)
  {
    G4Exception("R4DetectorConstruction::Read()", "R4GEOM001", FatalException,
                "No world volume found in the GDML file.");
  }
  fInitialized = true;
}

void R4DetectorConstruction::ListVolumes()
{
  if (!fWorld)
  {
    G4cout << "World volume is not yet constructed." << G4endl;
    return;
  }
  G4cout << "=== Logical volumes with sensitive detectors ===" << G4endl;
  for (auto* lv : *G4LogicalVolumeStore::GetInstance())
  {
    auto* sd = lv->GetSensitiveDetector();
    G4cout << "  LV <" << lv->GetName() << "> SD: "
           << (sd ? sd->GetName() : G4String("(none)")) << G4endl;
  }
  G4cout << "=== Physical volume tree (top) ===" << G4endl;
  auto* lv = fWorld->GetLogicalVolume();
  G4cout << "  " << fWorld->GetName()
         << "  [" << lv->GetMaterial()->GetName() << "]" << G4endl;
  for (G4int i = 0; i < lv->GetNoDaughters(); ++i)
  {
    auto* pv = lv->GetDaughter(i);
    G4cout << "    " << pv->GetName()
           << "  [" << pv->GetLogicalVolume()->GetMaterial()->GetName() << "]" << G4endl;
  }
  G4cout << "================================" << G4endl;
}
