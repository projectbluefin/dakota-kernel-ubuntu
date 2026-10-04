# Ubuntu 26.10 generic kernel; ported from the Ghost-verified Dakota recipe.
# Update the Ubuntu source with `just bst source track kernel.bst`.
kind: make
description: Ubuntu generic kernel, modules and matching development headers

build-depends:
- dakota.bst:freedesktop-sdk.bst:public-stacks/buildsystem-make.bst
- dakota.bst:freedesktop-sdk.bst:components/bison.bst
- dakota.bst:freedesktop-sdk.bst:components/cpio.bst
- dakota.bst:freedesktop-sdk.bst:components/flex.bst
- dakota.bst:freedesktop-sdk.bst:components/bc.bst
- dakota.bst:freedesktop-sdk.bst:components/gzip.bst
- dakota.bst:freedesktop-sdk.bst:components/pahole.bst
- dakota.bst:freedesktop-sdk.bst:components/python3.bst
- dakota.bst:freedesktop-sdk.bst:components/rsync.bst
- dakota.bst:freedesktop-sdk.bst:components/rust.bst
- dakota.bst:freedesktop-sdk.bst:components/rust-bindgen.bst
- dakota.bst:freedesktop-sdk.bst:components/rust-src.bst
- dakota.bst:freedesktop-sdk.bst:components/util-linux.bst
- dakota.bst:freedesktop-sdk.bst:components/zstd.bst
- filename: dakota.bst:freedesktop-sdk.bst:components/linux-module-cert.bst
  strict: true

variables:
  indep-libdir: '%{prefix}/lib'
  strip-binaries: ''
  kernel_arch: '%{arch}'
  src-arch: x86
  image-name: '$(make -s image_name)'
  optimize-debug: false

environment:
  ARCH: '%{kernel_arch}'
  KBUILD_BUILD_TIMESTAMP: 'Thu Nov 10 15:00:00 UTC 2011'
  KBUILD_BUILD_USER: tomjon
  MAXJOBS: '%{max-jobs}'
  RUST_LIB_SRC: '%{indep-libdir}/rustlib/src/rust/library'
  (?):
  - x86_64_v3:
      KCFLAGS: '-march=x86-64-v3 -mtune=skylake'

environment-nocache:
- MAXJOBS

config:
  configure-commands:
  - |
    python3 debian/scripts/misc/annotations --file debian.master/config/annotations --arch "%{go-arch}" --flavour generic --export > .config
    cat debian/certs/*.pem > debian/canonical-certs.pem
    cat debian/revoked-certs/*.pem > debian/canonical-revoked-certs.pem

  - |
    . ./.dakota-config/files/linux/config-utils.sh
    rm -f expected-configs
    enable CRYPTO_ZSTD
    . ./.dakota-config/files/linux/dakota-config.sh
    # Keep the established deterministic module signing/trust contract.
    if [ -f /keys/linux-module-cert.crt ]; then
      cat /keys/linux-module-cert.crt >> debian/canonical-certs.pem
    fi
    value_str MODULE_SIG_KEY ""
    remove MODULE_SIG_ALL
    ubuntu_version=$(python3 -c 'import re; print(re.search(r"\(([^)]+)\)", open("debian.master/changelog").readline()).group(1))')
    ubuntu_abi=${ubuntu_version#*-}
    value_str LOCALVERSION "-${ubuntu_abi%%.*}-generic-dakota"
    remove LOCALVERSION_AUTO
    enable RUST

  - |
    make -j1 olddefconfig

  - |
    . ./.dakota-config/files/linux/config-utils.sh
    missing_configs=0
    for config in $(cat expected-configs); do
      if ! has "${config}"; then
        echo "Missing ${config}" 1>&2
        missing_configs=1
      fi
    done
    [ "${missing_configs}" = 0 ]
    grep -q '^CONFIG_CRYPTO_ZSTD=y$' .config

  install-commands:
  - |
    release=$(make -s kernelrelease)
    install -Dm644 "%{image-name}" "%{install-root}%{indep-libdir}/modules/${release}/vmlinuz"
    install -Dm644 vmlinux "%{install-root}%{indep-libdir}/modules/${release}/vmlinux"
    install -Dm644 System.map "%{install-root}%{indep-libdir}/modules/${release}/System.map"
    install -Dm644 .config "%{install-root}%{indep-libdir}/modules/${release}/config"
    ZSTD_CLEVEL=19 make -j1 INSTALL_MOD_PATH="%{install-root}%{prefix}" INSTALL_MOD_STRIP=1 modules_install

  - |
    release=$(make -s kernelrelease)
    targetdir="%{install-root}%{prefix}/src/linux-${release}"
    rm "%{install-root}%{indep-libdir}/modules/${release}"/build
    to_copy=(
      Makefile
      Module.symvers
      .config
      "arch/%{src-arch}/include"
      "arch/%{src-arch}/Makefile"
      scripts
      include
    )
    if [ "$(scripts/config -s OBJTOOL)" = y ]; then
      to_copy+=(tools/objtool/objtool)
    fi
    for file in "${to_copy[@]}"; do
      targetfile="${targetdir}/${file}"
      dir="$(dirname "${targetfile}")"
      [ -d "${dir}" ] || install -d "${dir}"
      cp -aT "${file}" "${targetfile}"
    done
    ln -sr "${targetdir}" "%{install-root}%{indep-libdir}/modules/${release}/build"

  - |
    %{install-extra}

public:
  bst:
    split-rules:
      devel:
        (>):
        - '%{indep-libdir}/modules/*/System.map'
        - '%{indep-libdir}/modules/*/vmlinux'
    overlap-whitelist:
    - '%{project_licensedir}'
    - '%{project_licensedir}/**'

sources:
- kind: git_repo
  url: launchpad:~ubuntu-kernel/ubuntu/+source/linux/+git/stonking
  track: Ubuntu-7.3.0-*
  ref: Ubuntu-7.3.0-8.8-0-gd03cf7a92919b0e6ab4e4a756dec41542eb2040f
# Share the tested configuration helpers without maintaining duplicate copies.
- kind: git_repo
  url: github:projectbluefin/dakota.git
  ref: 39d128aa9dfa66d73a6b48cefc70efdc1808766d
  directory: .dakota-config
