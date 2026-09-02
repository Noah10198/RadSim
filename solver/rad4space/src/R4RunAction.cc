//
// R4RunAction.cc
//   Minimal analysis-file handling with native G4AnalysisManager.
//

#include "R4RunAction.hh"

#include "G4AnalysisManager.hh"
#include "G4GenericMessenger.hh"
#include "G4Run.hh"
#include "G4TScoreHistFiller.hh"

R4RunAction::R4RunAction()
{
  auto* analysisManager = G4AnalysisManager::Instance();
  analysisManager->SetDefaultFileType("csv");
  analysisManager->SetVerboseLevel(0);

  // Native scorer -> 1-D histogram filling (Book 4.9.8).
  // Without this, /score/fill1D binds nothing and histograms stay empty.
  new G4TScoreHistFiller<G4AnalysisManager>();

  messenger = new G4GenericMessenger(this, "/rad4space/analysis/",
                                     "rad4space analysis commands");
  auto& fnCmd = messenger->DeclareProperty("filename", fFileName,
                                           "Output file base name");
  fnCmd.SetToBeBroadcasted(false);
}

R4RunAction::~R4RunAction()
{
  delete messenger;
}

void R4RunAction::BeginOfRunAction(const G4Run* /*run*/)
{
  if (!fFileOpen)
  {
    auto* analysisManager = G4AnalysisManager::Instance();
    analysisManager->OpenFile(fFileName);
    fFileOpen = true;
  }
}

void R4RunAction::EndOfRunAction(const G4Run* /*run*/)
{
  auto* analysisManager = G4AnalysisManager::Instance();
  analysisManager->Write();
  analysisManager->CloseFile();
  fFileOpen = false;
}
