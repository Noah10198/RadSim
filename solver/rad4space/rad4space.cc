//
// ********************************************************************
// * License and Disclaimer                                           *
// *                                                                  *
// *  This software is provided under the terms and conditions of the *
// *  Geant4 Software License, included in the file LICENSE.          *
// ********************************************************************
//
// rad4space.cc
//   Main program of rad4space
//
//   Minimal, native-Geant4 style radiation solver :
//     - GDML import (like Gorad)
//     - Multi-threaded (G4RunManagerFactory)
//     - Replaceable reference physics list (G4PhysListFactory)
//     - General Particle Source (like exgps)
//     - Native command-based scoring (like RE03) and 1-D histogram
//       filling via G4TScoreHistFiller (G4 Book For Application
//       Developers, 4.9.8 Filling 1-D histogram)
//

#include "G4Types.hh"

#include "G4RunManagerFactory.hh"
#include "G4ScoringManager.hh"
#include "G4UImanager.hh"
#include "G4UIExecutive.hh"
#include "G4VisExecutive.hh"
#include "G4Threading.hh"
#include "G4UIcommand.hh"

#include "R4DetectorConstruction.hh"
#include "R4PhysicsList.hh"
#include "R4ActionInitialization.hh"

int main(int argc, char** argv)
{
  // Instantiate G4UIExecutive if there are no arguments (interactive mode).
  // Explicitly request the Qt session so the geometry can be rendered inside
  // a Qt window (vis.mac uses the OGLIQt driver).
  G4UIExecutive* ui = nullptr;
  if (argc == 1) ui = new G4UIExecutive(argc, argv, "Qt");

  // Construct the run manager.
  //   argv[2] : thread count (MT/tasking, default) or "serial"
  //   (serial is needed for /score/create/realWorldLogVol scoring,
  //    which is not recorded correctly in multi-threaded mode)
  G4RunManagerType rmType = G4RunManagerType::Default;
  G4int nThreads = G4Threading::G4GetNumberOfCores();
  if (argc == 3)
  {
    G4String arg = argv[2];
    if (arg == "serial") rmType = G4RunManagerType::Serial;
    else nThreads = G4UIcommand::ConvertToInt(argv[2]);
  }
  auto* runManager = G4RunManagerFactory::CreateRunManager(rmType);
  if (rmType != G4RunManagerType::Serial)
  {
    runManager->SetNumberOfThreads(nThreads);
    G4cout << "rad4space running with " << nThreads << " thread(s)" << G4endl;
  }
  else
  {
    G4cout << "rad4space running in serial mode" << G4endl;
  }

  // Activate UI-command based scoring (native, RE03 style)
  G4ScoringManager::GetScoringManager()->SetVerboseLevel(1);

  // Set mandatory initialization classes
  runManager->SetUserInitialization(new R4DetectorConstruction);
  runManager->SetUserInitialization(new R4PhysicsList);
  runManager->SetUserInitialization(new R4ActionInitialization);

  // Visualization manager
  G4VisManager* visManager = nullptr;
  G4UImanager* UImanager = G4UImanager::GetUIpointer();

  if (ui)   // interactive mode
  {
    visManager = new G4VisExecutive;
    visManager->Initialize();
    UImanager->ApplyCommand("/control/execute vis.mac");
    ui->SessionStart();
    delete ui;
  }
  else     // batch mode
  {
    G4String command = "/control/execute ";
    G4String fileName = argv[1];
    UImanager->ApplyCommand(command + fileName);
  }

  // Job termination
  delete visManager;
  delete runManager;

  return 0;
}
