# pipoe

The objective of this project is to make creating OpenEmbedded python recipes just a bit easier. `pipoe` will take either a single package name or a requirements file and recursively generate bitbake recipes for every pypi package listed. It is not guaranteed that it will work for every package. Additionally, many recipes will still require additional modification after generation (patches, overrides, appends, etc.). In those cases it is recommended that the user add these modifications in a bbappend file.

## Install
```
> pip3 install pipoe
```

## Licenses

Licensing within OE is typically pretty strict. `pipoe` contains a license map which will attempt to map a packages license to one that will be accepted by the OE framework. If a license string is found which cannot be mapped, the user will be prompted to enter a valid license name. This mapping will be saved and the updated map will be saved to `./licenses.py` if the `--licenses` flag is provided. It is recommended that this file be PR'ed to this repository when generally useful changes are made.

## Extras
`pipoe` supports generating "extra" recipes based on the extra feature declarations in the packages `requires_dist` field (i.e. urllib3\[secure\]). These recipes are generated as packagegroups which rdepend on the base package.


## Versions
By default `pipoe` will generate a recipe for the newest version of a package. Supplying the `--version` argument will override this behavior. Additionally, `pipoe` will automatically parse versions from requirements files.

## Example

```
> pipoe --help
usage: pipoe [-h] [--package PACKAGE] [--version VERSION]
             [--requirements REQUIREMENTS] [--extras] [--outdir OUTDIR]
             [--python {python,python3}] [--licenses]
             [--default-license DEFAULT_LICENSE]

optional arguments:
  -h, --help            show this help message and exit
  --package PACKAGE, -p PACKAGE
                        The package to process.
  --version VERSION, -v VERSION
                        The package version.
  --requirements REQUIREMENTS, -r REQUIREMENTS
                        The pypi requirements file.
  --extras, -e          Generate recipes for extras.
  --outdir OUTDIR, -o OUTDIR
                        The recipe directory.
  --python {python,python3}, -y {python,python3}
                        The python version to use.
  --licenses, -l        Output an updated license map upon completion.
  --default-license DEFAULT_LICENSE, -d DEFAULT_LICENSE
                        The default license to use when the package license
                        cannot be mapped.
  --pypi, -s            Use oe pypi class for recipe
  --yocto-layers-dir    Can be used together if --existing-packages to generate
                        the existing packages in the yocto build system.
  --existing-packages   A pypi requirements file containing the existing packages
                        in the enviroment.
  --write-preferred     Flag indicating if the preferred packages file should be
                        created.

> pipoe -p requests
Gathering info:
  requests
  | chardet
  | idna
  | urllib3
  | certifi
Generating recipes(5):
  python-requests_2.21.0.bb
  python-chardet_3.0.4.bb
  python-idna_2.8.bb
  python-urllib3_1.24.1.bb
  python-certifi_2018.11.29.bb

License mappings are available in: ./licenses.py
PREFERRED_VERSIONS are available in: ./python-versions.inc

> pipoe --yocto-layers-dir ~/hgp-build --existing-packages requirements.txt
Gathering recipes in Yocto layers directory: ~/hgp-build
Could not parse: ~/hgp-build/meta-openembedded/meta-oe/recipes-devtools/flatbuffers/python3-flatbuffers.bb
Could not parse: ~/hgp-build/meta-openembedded/meta-oe/recipes-printing/cups/python3-pycups.bb
Could not parse: ~/hgp-build/meta-openembedded/meta-python/recipes-devtools/python/python3-systemd_235.bb
Could not parse: ~/hgp-build/meta-openembedded/meta-python/recipes-devtools/python/python3-inotify_git.bb
Could not parse: ~/hgp-build/meta-openembedded/meta-python/recipes-extended/python-cson/python3-cson_git.bb
Could not parse: ~/hgp-build/meta-virtualization/recipes-devtools/python/python3-sphinx-420.bb
Could not parse: ~/hgp-build/meta-virtualization/recipes-devtools/python/python3-udica_git.bb
Existing packages are available in: requirements.txt

> pipoe -p codechecker -v 6.25.1 --existing-packages requirements.txt
Gathering info:
  codechecker==6.25.1
  | [WARNING] Package lxml version needed 5.3.0 found 5.0.2
  | lxml==5.3.0
  | [WARNING] Package setuptools version needed 70.2.0 found 69.1.1
  | setuptools==70.2.0
  | gitpython==3.1.41
  | types-PyYAML==6.0.12.12
  | sarif-tools==1.0.0
  |-- python-docx
  | PyYAML==6.0.1
  | multiprocess==0.70.15
Generating recipes (9):
  python3-codechecker_6.25.1.bb
  python3-lxml_5.3.0.bb
  python3-setuptools_70.2.0.bb
  python3-gitpython_3.1.41.bb
  python3-types-pyyaml_6.0.12.12.bb
  python3-sarif-tools_1.0.0.bb
  python3-python-docx_1.1.2.bb
  python3-pyyaml_6.0.1.bb
  python3-multiprocess_0.70.15.bb
```