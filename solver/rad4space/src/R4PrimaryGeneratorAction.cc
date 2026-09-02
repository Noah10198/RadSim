//
// R4PrimaryGeneratorAction.cc
//   General Particle Source based primary generator (like exgps).
//

#include "R4PrimaryGeneratorAction.hh"

#include "G4Event.hh"
#include "G4GeneralParticleSource.hh"

R4PrimaryGeneratorAction::R4PrimaryGeneratorAction()
{
  fGPS = new G4GeneralParticleSource();
}

R4PrimaryGeneratorAction::~R4PrimaryGeneratorAction()
{
  delete fGPS;
}

void R4PrimaryGeneratorAction::GeneratePrimaries(G4Event* event)
{
  fGPS->GeneratePrimaryVertex(event);
}
