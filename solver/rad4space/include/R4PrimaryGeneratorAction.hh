//
// R4PrimaryGeneratorAction.hh
//   General Particle Source based primary generator (like exgps).
//

#ifndef R4PrimaryGeneratorAction_h
#define R4PrimaryGeneratorAction_h 1

#include "G4VUserPrimaryGeneratorAction.hh"
#include "globals.hh"

class G4GeneralParticleSource;
class G4Event;

class R4PrimaryGeneratorAction : public G4VUserPrimaryGeneratorAction
{
  public:
    R4PrimaryGeneratorAction();
    ~R4PrimaryGeneratorAction() override;

    void GeneratePrimaries(G4Event*) override;

  private:
    G4GeneralParticleSource* fGPS = nullptr;
};

#endif
