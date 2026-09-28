# Deploying on a server without a GPU

Generation runs on the CPU; a 32-bar level takes about 5–12 s on one or two cores.
The server needs the Python package (`package.nix`), the trained model and the built
web app. Training data is not needed: without `data/processed/train.jsonl` the
filter that rejects copies of training melodies is off, which is logged at startup
and shown as `"copy_check": false` on `/health`.

## What goes where

| On the server | Comes from |
|---|---|
| The `mb` command | `package.nix`, built with the system's nixpkgs (CPU torch) |
| `~/mockingbird/models/melody-v1.pt`, `difficulty_thresholds.json` | the local `models/` (not in git) |
| `~/mockingbird/web/` | `npm --prefix web run build`, then the contents of `web/dist` |

The web app is built locally rather than in Nix: Vite and TypeScript ship prebuilt
native binaries that would need patching inside the Nix sandbox.

```bash
npm --prefix web run build
ssh server mkdir -p mockingbird/models mockingbird/web
scp models/melody-v1.pt models/difficulty_thresholds.json server:mockingbird/models/
scp -r web/dist/* server:mockingbird/web/
```

## Service (NixOS module)

The package is fetched at a fixed commit and built with the system's own `pkgs`, so
this works from any module without touching the system flake. `sha256` is the hash
of the commit's tarball: leave it as `lib.fakeSha256` once, and the rebuild error
prints the real value. Updating means changing `rev` and the hash.

```nix
{ lib, pkgs, ... }:
let
  rev = "<commit>";
  src = builtins.fetchTarball {
    url = "https://github.com/TehMillhouse/mockingbird/archive/${rev}.tar.gz";
    sha256 = lib.fakeSha256;
  };
  mockingbird = pkgs.callPackage "${src}/package.nix" { };
in {
  systemd.services.mockingbird = {
    description = "Mockingbird sight-singing trainer";
    wantedBy = [ "multi-user.target" ];
    after = [ "network.target" ];
    environment.MOCKINGBIRD_WEB = "/home/max/mockingbird/web";
    serviceConfig = {
      User = "max";
      WorkingDirectory = "/home/max/mockingbird";
      ExecStart = "${mockingbird}/bin/mb serve --port 8765"
        + " --model /home/max/mockingbird/models/melody-v1.pt";
      Restart = "on-failure";
    };
  };
}
```

`mb serve` binds to 127.0.0.1. Run a single process: levels are kept in memory, and
the page fetches a level's ABC export in a second request, which another worker
would not know.

`flake.nix` exposes the same package (`nix build github:TehMillhouse/mockingbird`)
for trying it out by hand.

## nginx under a path prefix

The web app uses relative URLs throughout, so any prefix works as long as nginx
strips it (the trailing slash on `proxyPass`) and the page URL ends in a slash:

```nix
services.nginx.virtualHosts."trollbu.de".locations = {
  "= /mockingbird".return = "301 /mockingbird/";
  "/mockingbird/".proxyPass = "http://127.0.0.1:8765/";
};
```

HTTPS is required: browsers only allow microphone access on secure pages.

The piano samples load from `tonejs.github.io` at runtime.
