kind: script

build-depends:
- dakota.bst:freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- dakota.bst:freedesktop-sdk.bst:components/oci-builder.bst
- filename: kernel.bst
  config:
    location: /kernel
- filename: license.bst
  config:
    location: /license

config:
  commands:
  - |
    install -Dm644 /license/LICENSE /kernel/usr/share/licenses/dakota-kernel-ubuntu/LICENSE
  - |
    cd "%{install-root}"
    build-oci <<EOF
    mode: oci
    gzip: disabled
    images:
    - os: linux
      architecture: "%{go-arch}"
      layer: /kernel
      comment: "Ubuntu kernel, modules and development headers"
      config:
        Labels:
          org.opencontainers.image.title: Dakota Ubuntu kernel
          org.opencontainers.image.description: Kernel-only filesystem for BuildStream consumers; not a bootable image
          org.opencontainers.image.source: https://github.com/projectbluefin/dakota-kernel-ubuntu
          org.opencontainers.image.licenses: GPL-2.0-only
          org.opencontainers.image.version: Ubuntu-7.3.0-8.8
          io.projectbluefin.dakota.config-revision: 39d128aa9dfa66d73a6b48cefc70efdc1808766d
      index-annotations:
        org.opencontainers.image.ref.name: ghcr.io/projectbluefin/dakota-kernel-ubuntu:latest
    EOF
