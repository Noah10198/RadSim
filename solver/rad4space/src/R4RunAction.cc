//
// R4RunAction.cc
//   Minimal analysis-file handling with native G4AnalysisManager.
//   Plus one-shot trajectory dump to Traj.csv (see R4RunAction.hh).
//

#include "R4RunAction.hh"

#include "G4AnalysisManager.hh"
#include "G4GenericMessenger.hh"
#include "G4ios.hh"
#include "G4ParticleDefinition.hh"
#include "G4ParticleTable.hh"
#include "G4Run.hh"
#include "G4TScoreHistFiller.hh"

#include <atomic>
#include <fstream>
#include <iomanip>
#include <vector>

namespace
{
  // HARD-CODED LIMITS - edit here:
  //   Record at most this many whole events from the elected recorder
  //   worker.  0 = unlimited.  If >0, an event is only ever started when the
  //   count of already-recorded events is below this limit (tracks are never
  //   cut mid-way).
  const G4int kMaxRecordEvents = 0;

  //   Hard resource cap on the whole Traj.csv: stop at a track boundary once
  //   this many points are stored, so every written track stays complete.
  const G4int kMaxTrajPoints = 5000;

  // Process-wide trajectory store.
  //   Writer: the single elected recorder worker, during event processing.
  //   Reader: master's EndOfRunAction, after the whole run has finished, so
  //   no locking is needed around the vector itself.
  std::vector<R4TrajPoint> gTraj;
  std::atomic<bool> gRecorderTaken{false};
  G4bool gStop = false;
  G4int  gEventCount = 0;
  G4int  gLastEventID = -1;
  G4int  gLastTrackID = -1;
}

//....oooOO0OOooo........oooOO0OOooo........oooOO0OOooo........oooOO0OOooo......

R4RunAction::R4RunAction()
{
  auto* analysisManager = G4AnalysisManager::Instance();
  analysisManager->SetDefaultFileType("csv");
  analysisManager->SetVerboseLevel(0);

  new G4TScoreHistFiller<G4AnalysisManager>();

  messenger = new G4GenericMessenger(this, "/rad4space/analysis/",
                                     "rad4space analysis commands");
  auto& fnCmd = messenger->DeclareProperty("filename", fFileName,
                                           "Output file base name");
  fnCmd.SetToBeBroadcasted(false);
}

//....oooOO0OOooo........oooOO0OOooo........oooOO0OOooo........oooOO0OOooo......

R4RunAction::~R4RunAction()
{
  delete messenger;
}

//....oooOO0OOooo........oooOO0OOooo........oooOO0OOooo........oooOO0OOooo......

void R4RunAction::BeginOfRunAction(const G4Run* /*run*/)
{
  if (!fFileOpen)
  {
    auto* analysisManager = G4AnalysisManager::Instance();
    analysisManager->OpenFile(fFileName);
    fFileOpen = true;
  }

  // Reset the shared trajectory store once per run.  The master's
  // BeginOfRunAction runs before any worker starts stepping.
  if (IsMaster())
  {
    gTraj.clear();
    gRecorderTaken = false;
    gStop = false;
    gEventCount = 0;
    gLastEventID = -1;
    gLastTrackID = -1;
  }
}

//....oooOO0OOooo........oooOO0OOooo........oooOO0OOooo........oooOO0OOooo......

void R4RunAction::EndOfRunAction(const G4Run* run)
{
  G4int nofEvents = run->GetNumberOfEvent();
  if (nofEvents == 0) return;

  auto* analysisManager = G4AnalysisManager::Instance();
  analysisManager->Write();
  analysisManager->CloseFile();
  fFileOpen = false;

  // One-shot trajectory dump.  Only the master runs after every worker has
  // finished (shared store complete), so write here.
  if (IsMaster() && !gTraj.empty()) WriteTrajFile();

  if (IsMaster()) {
    G4cout << G4endl << "--------------------End of Global Run-----------------------";
  }
  else {
    G4cout << G4endl << "--------------------End of Local Run------------------------";
  }
  G4cout << G4endl << " The run consists of " << nofEvents << " " << G4endl
         << "------------------------------------------------------------" << G4endl << G4endl;
}

//....oooOO0OOooo........oooOO0OOooo........oooOO0OOooo........oooOO0OOooo......

G4bool R4RunAction::ClaimRecorder()
{
  // Atomically set the "taken" flag and return its previous value.
  // Exactly one caller (the first) sees false and becomes the recorder.
  return !gRecorderTaken.exchange(true);
}

//....oooOO0OOooo........oooOO0OOooo........oooOO0OOooo........oooOO0OOooo......

void R4RunAction::RecordTrajPoint(G4int eventID, G4int trackID, G4int parentID,
                                  G4int pdg, G4int step,
                                  G4double x, G4double y, G4double z)
{
  if (gStop) return;

  // New event?
  if (eventID != gLastEventID)
  {
    if (kMaxRecordEvents > 0 && gEventCount >= kMaxRecordEvents)
    {
      gStop = true;
      G4cout << "[Traj] event cap " << kMaxRecordEvents
             << " reached; further events not recorded." << G4endl;
      return;
    }
    ++gEventCount;
    gLastEventID = eventID;
    gLastTrackID = -1;   // force the next point to open a new track
  }

  // New track: only start it while below the point cap, so every written
  // track stays complete.
  if (trackID != gLastTrackID)
  {
    if (gTraj.size() >= static_cast<std::size_t>(kMaxTrajPoints))
    {
      gStop = true;
      G4cout << "[Traj] point cap " << kMaxTrajPoints
             << " reached; further tracks not recorded." << G4endl;
      return;
    }
    gLastTrackID = trackID;
  }

  gTraj.push_back(R4TrajPoint{eventID, trackID, parentID, pdg, step,
                              x, y, z});
}

//....oooOO0OOooo........oooOO0OOooo........oooOO0OOooo........oooOO0OOooo......

G4bool R4RunAction::TrajStopped() const
{
  return gStop;
}

//....oooOO0OOooo........oooOO0OOooo........oooOO0OOooo........oooOO0OOooo......

void R4RunAction::WriteTrajFile()
{
  std::ofstream out("Traj.csv", std::ios::out | std::ios::trunc);
  if (!out.is_open())
  {
    G4ExceptionDescription ed;
    ed << "Cannot open Traj.csv for writing.";
    G4Exception("R4RunAction::WriteTrajFile", "Traj002", JustWarning, ed);
    return;
  }

  out << "eventID,trackID,parentID,particle,step,x,y,z\n";
  out << std::setprecision(8);

  auto* table = G4ParticleTable::GetParticleTable();
  for (const auto& p : gTraj)
  {
    G4String particle = "?";
    const G4ParticleDefinition* def = table->FindParticle(p.pdg);
    if (def) particle = def->GetParticleName();

    out << p.eventID << ','
        << p.trackID << ','
        << p.parentID << ','
        << particle << ','
        << p.step << ','
        << p.x << ',' << p.y << ',' << p.z << '\n';
  }
  out.close();

  G4cout << "[Traj] wrote " << gTraj.size() << " points to Traj.csv" << G4endl;
}
