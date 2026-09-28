# Deploying on a server without a GPU

Generation runs on the CPU; a 32-bar level takes about 5–12 s on one or two cores.
The server needs the Python package (from `flake.nix`), the trained model and the
built web app. Training data is not needed: without `data/processed/train.jsonl` the
filter that rejects copies of training melodies is off, which is logged at startup
and shown as `"copy_check": false` on `/health`.

## What goes where

| On the server | Comes from |
|---|---|
| The `mb` command | `nix build` of this repository's flake (nixpkgs' CPU torch, Python 3.13) |
| `~/mockingbird/models/melody-v1.pt`, `difficulty_thresholds.json` | the local `models/` (not in git) |
| `~/mockingbird/web/` | `npm --prefix web run build`, then the contents of `web/dist` |

The web app is built locally rather than in Nix: Vite and TypeScript ship prebuilt
native binaries that would need patching inside the Nix sandbox.

```bash
npm --prefix web run build
rsync -a models/melody-v1.pt models/difficulty_thresholds.json server:mockingbird/models/
rsync -a --delete web/dist/ server:mockingbird/web/
```

## Service (home-manager)

With this repository as a flake input `mockingbird`:

```nix
{ pkgs, inputs, ... }: {
  systemd.user.services.mockingbird = {
    Unit.Description = "Mockingbird sight-singing trainer";
    Install.WantedBy = [ "default.target" ];
    Service = {
      ExecStart = "${inputs.mockingbird.packages.${pkgs.system}.default}/bin/mb serve"
        + " --port 8765 --model %h/mockingbird/models/melody-v1.pt";
      Environment = [ "MOCKINGBIRD_WEB=%h/mockingbird/web" ];
      WorkingDirectory = "%h/mockingbird";
      Restart = "on-failure";
    };
  };
}
```

`mb serve` binds to 127.0.0.1. A user service only runs while its user is logged in
unless lingering is on (`users.users.<name>.linger = true;` in the system
configuration, or `loginctl enable-linger` once).

Run a single process. Levels are kept in memory, and the page fetches a level's
ABC export in a second request, which another worker would not know.

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
