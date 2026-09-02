//
// R4DetectorConstruction.hh
//   Geometry imported from a GDML file (like Gorad).
//

#ifndef R4DetectorConstruction_h
#define R4DetectorConstruction_h 1

#include "G4VUserDetectorConstruction.hh"
#include "globals.hh"

class G4VPhysicalVolume;
class G4GDMLParser;
class G4GenericMessenger;

class R4DetectorConstruction : public G4VUserDetectorConstruction
{
  public:
    R4DetectorConstruction();
    ~R4DetectorConstruction() override;

    G4VPhysicalVolume* Construct() override;
    void ConstructSDandField() override;

    // UI helper : print the top of the physical volume tree
    void ListVolumes();

  private:
    void Read();

    G4GDMLParser* parser = nullptr;
    G4GenericMessenger* messenger = nullptr;
    G4VPhysicalVolume* fWorld = nullptr;
    G4String fGDMLFile = "simpleCone.gdml";
    G4bool fInitialized = false;
};

#endif
