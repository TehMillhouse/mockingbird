# The service as a plain Nix package, buildable with any nixpkgs:
#   pkgs.callPackage ./package.nix { }
# Generation runs on nixpkgs' CPU build of torch.
{ python3, fetchurl }:

let
  py = python3.pkgs;

  # not in nixpkgs; its PyPI wheel is pure Python
  music21 = py.buildPythonPackage {
    pname = "music21";
    version = "10.5.0";
    format = "wheel";
    src = fetchurl {
      url = "https://files.pythonhosted.org/packages/81/4c/4f307e5ab6fbf59233813e58e07128a599c810dd974673449e132ce1432d/music21-10.5.0-py3-none-any.whl";
      sha256 = "9924eff5fbf58490e67cbf3b78a58ba53040e77c281930d354af32a747e94606";
    };
    dependencies = with py; [ chardet joblib jsonpickle matplotlib more-itertools numpy requests webcolors ];
  };
in
py.buildPythonApplication {
  pname = "mockingbird";
  version = "0.1.0";
  pyproject = true;
  src = ./.;
  build-system = [ py.hatchling ];
  dependencies = (with py; [ torch numpy pydantic fastapi uvicorn typer ]) ++ [ music21 ];
  # only used to build the training corpus, not to serve levels
  pythonRemoveDeps = [ "ms3" "pandas" ];
  # take nixpkgs' versions
  pythonRelaxDeps = true;
  doCheck = false;
  pythonImportsCheck = [ "mockingbird.api.app" ];
}
