{
  description = "Mockingbird: sight-singing level generator and its HTTP API (CPU)";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
    in
    {
      packages.${system}.default = nixpkgs.legacyPackages.${system}.callPackage ./package.nix { };
    };
}
