# Dakota Ubuntu kernel

BuildStream 2 producer for `ghcr.io/projectbluefin/dakota-kernel-ubuntu`: an Ubuntu-source kernel compiled remotely by GitHub Actions, reusable by Dakota or any BuildStream project. No Ubuntu packages, RPMs, or prebuilt distribution kernels are used.

## Current scope and source

- **x86_64 only** (`linux/amd64` in OCI); no multiarch promise.
- Ubuntu 26.10 (Stonking) source tag **Ubuntu-7.3.0-8.8**, peeled source commit `d03cf7a92919b0e6ab4e4a756dec41542eb2040f` (annotated tag object `664a2f84fd2459e2cdd2b0eed45a89bfee3776ef`), from [Launchpad](https://git.launchpad.net/~ubuntu-kernel/ubuntu/+source/linux/+git/stonking/tag/?h=Ubuntu-7.3.0-8.8).
- This is a **release-candidate kernel**, not a stable 7.3 release: module/kernel release **`7.3.0-rc5-8-generic-dakota`**.
- [Toolchain/configuration pin](https://github.com/projectbluefin/dakota/tree/39d128aa9dfa66d73a6b48cefc70efdc1808766d): `elements/dakota.bst` fixes the SDK junction to `39d128aa9dfa66d73a6b48cefc70efdc1808766d`, with `arch: x86_64`, `gaming: false`, `x86_64_v3: false`. This repository owns the source-building [kernel recipe](elements/kernel.bst), so Dakota can consume its registry output without owning the producer recipe.
- Configuration starts with [Ubuntu generic annotations](https://git.launchpad.net/~ubuntu-kernel/ubuntu/+source/linux/+git/stonking/tree/debian.master/config/annotations?h=Ubuntu-7.3.0-8.8), then sources [Dakota configuration helpers](https://github.com/projectbluefin/dakota/tree/39d128aa9dfa66d73a6b48cefc70efdc1808766d/files/linux) from a separately pinned Git source. The recipe requires `CONFIG_RUST=y` and built-in `CONFIG_CRYPTO_ZSTD=y`.
- `CONFIG_SECURITY_SELINUX=y`, but the default LSM list is `landlock,lockdown,yama,integrity,apparmor,bpf`: SELinux is not selected by default. Consumers requiring SELinux must configure and verify the active LSM at boot, not infer enforcement from compiled support.

The image is a **scratch filesystem artifact**, not a runnable container or bootable OS. It has no userspace, initramfs, bootloader, or Ubuntu Secure Boot signature. Modules are **unsigned**, matching the pinned Dakota policy; registry signing does not sign the kernel or its modules. A successful build/publication is not a boot test. Dakota's native composefs boot test remains blocked elsewhere and is not resolved by this producer.

BuildStream produces an OCI layout internally. GHCR serves a gzip-compressed Docker-v2 manifest so the released `buildstream-plugins==2.5.0` Docker source works without an OCI-support patch. Conversion preserves the uncompressed filesystem digest; publication verifies and signs the **registry manifest digest after conversion**, not the internal OCI manifest digest.

## Filesystem contract

The complete kernel artifact is preserved, including development files:

```text
/usr/lib/modules/<kernel-release>/
  vmlinuz, config, System.map, vmlinux
  kernel/...                       # installed modules
  modules.*                        # module metadata
  build -> ../../../src/linux-<kernel-release>
/usr/src/linux-<kernel-release>/    # matching module build headers/scripts,
                                   # .config and Module.symvers
/usr/share/licenses/dakota-kernel-ubuntu/LICENSE
```

Consumers choose runtime/development splits rather than the producer discarding headers. The `build` symlink and its `/usr/src` target must travel together when compiling external modules. These headers are not the complete corresponding kernel source.

## Remote build and publication

Use the repository's [Actions page](https://github.com/projectbluefin/dakota-kernel-ubuntu/actions) to dispatch the build on `development` (the initial default branch), or use an authenticated GitHub CLI account with workflow permission:

```sh
gh workflow run build.yml --repo projectbluefin/dakota-kernel-ubuntu --ref development
gh run list --repo projectbluefin/dakota-kernel-ubuntu --branch development --limit 5
gh run watch --repo projectbluefin/dakota-kernel-ubuntu RUN_ID --interval 60
gh run view --repo projectbluefin/dakota-kernel-ubuntu RUN_ID --log
```

Replace `RUN_ID` with the actual listed run ID. Compilation happens on the remote runner through the pinned BuildStream container. The producer command is `just build`: it builds `kernel-image.bst` and checks the OCI layout out to `oci/`. `just bst <ARGS>` exposes the same pinned BST2 Podman wrapper; `BST_FLAGS` supplies optional global BST flags. Run these commands on a remote Linux builder, not as a local compilation prerequisite.

GHA restores BuildStream's native source/artifact cache and saves it even if a later packaging step fails. BuildStream's content keys decide which artifacts remain valid after source, configuration or toolchain changes; an OCI-only change does not require recompiling an unchanged kernel. Cache retention is best-effort under GitHub's storage quota. Cold builds use the SDK's upstream artifact caches before compiling missing elements. README-only pushes do not launch another build; use manual dispatch when wanted.

Published immutable tags have the syntax **`sha-<40-character producer commit>`**. Tags identify producer commits, not the upstream kernel commit. The default branch updates the following aliases only after digest verification and signing:

| Tag | What it follows |
| --- | --- |
| `latest` | Latest validated Ubuntu development kernel produced here |
| `ubuntu-26.10` | Latest producer build for Ubuntu 26.10 |
| `ubuntu-26.10-amd64` | Ubuntu 26.10's x86_64 build |
| `7.3` | Latest build in kernel series 7.3, **including release candidates** |
| `7.3.0-rc5` | Latest Ubuntu/configuration rebuild based on upstream 7.3.0-rc5 |
| `kernel-7.3.0-rc5-8-generic-dakota` | Latest rebuild with this exact `uname -r` |
| `ubuntu-7.3.0-8.8` | Latest producer rebuild of this exact Ubuntu source release |
| `sha-<producer commit>` / `@sha256:<digest>` | Exact immutable producer build / registry bytes |

Version aliases can move when configuration or packaging is rebuilt. Resolve and review a tag, then pin its digest in BST. No `stable` tag is advertised for an RC kernel. Tag families are derived from the verified build receipt, not a separate hand-maintained tag list.

Registry labels include the full kernel release/series/upstream version, architecture, Ubuntu release/codename/source tag/source commit/source URL, SDK/configuration commit, producer revision, vendor/authors, GPL license, and repository/documentation URLs. Standard `org.opencontainers.image.version` is the full kernel release; `revision` is the producer commit, not the SDK commit. `created` is that commit's timestamp for reproducibility; the kernel's fixed KBUILD timestamp remains separate. `oci_manifest_digest` in the build receipt is the internal artifact digest, not the converted registry digest.

```sh
skopeo inspect --no-creds --no-tags docker://ghcr.io/projectbluefin/dakota-kernel-ubuntu:7.3 | jq '{Digest, Architecture, Labels}'
```

Already-published SHA tags and digests are never rewritten to add labels; newly signed builds carry updated metadata.

For the documented `7.3.0-rc5-8-generic-dakota` release, the [successful signed publication](https://github.com/projectbluefin/dakota-kernel-ubuntu/actions/runs/37195816451) used producer commit `e8183d948b32ff2efa957c716fd04fa77eb76de6`:

```text
ghcr.io/projectbluefin/dakota-kernel-ubuntu@sha256:4e2ce6dfe1c2976115ad2f1c50aece4e865a2528adf839388983fcfc725db655
```

Its bare BST `ref` is `4e2ce6dfe1c2976115ad2f1c50aece4e865a2528adf839388983fcfc725db655`. This reference is anonymously readable and was fetched/imported remotely with unpatched `buildstream-plugins==2.5.0`, including the matching development headers and `build` symlink.

### One-time maintainer package visibility

For a new private GHCR package, an organization/package administrator must open the [package](https://github.com/orgs/projectbluefin/packages/container/dakota-kernel-ubuntu), choose **Package settings → Danger Zone → Change visibility → Public**, and confirm the package name. A public source repository alone does not guarantee public package visibility. Public visibility cannot be reverted to private. See [GitHub's access/visibility documentation](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility). Keep repository permission inheritance enabled; no consumer token is needed once public. Check anonymous access with the commands below before requesting any visibility change.

### Acquire a real public digest

Public GHCR reads need no login or personal access token. With `skopeo`, `jq`, and `sha256sum` available, query a published tag and select its `linux/amd64` manifest. This handles both a single manifest and an OCI index without assuming the tag's shape:

```sh
set -eu
IMAGE=ghcr.io/projectbluefin/dakota-kernel-ubuntu
TAG=latest # or the actual sha-<producer commit> tag from a successful run
skopeo inspect --no-creds --raw "docker://${IMAGE}:${TAG}" > kernel-manifest.json
if jq -e '.manifests' kernel-manifest.json >/dev/null; then
  DIGEST=$(jq -er '[.manifests[] | select(.platform.os == "linux" and .platform.architecture == "amd64")] | if length == 1 then .[0].digest else error("expected one linux/amd64 manifest") end' kernel-manifest.json)
else
  DIGEST=sha256:$(sha256sum kernel-manifest.json | cut -d ' ' -f 1)
fi
skopeo inspect --no-creds "docker://${IMAGE}@${DIGEST}" |
  jq -e '.Os == "linux" and .Architecture == "amd64"'
KERNEL_REF=${DIGEST#sha256:}
printf 'OCI manifest: %s@%s\nBuildStream ref: %s\n' "$IMAGE" "$DIGEST" "$KERNEL_REF"
```

Keep the printed digest with the producer commit/run provenance. There is deliberately no invented published digest in this README. BuildStream's Docker source requires the **bare 64-hex digest**, without the `sha256:` prefix.

Verify the keyless publisher signature with [Cosign](https://github.com/sigstore/cosign#verify-a-container-image) before committing that digest:

```sh
cosign verify \
  --certificate-identity 'https://github.com/projectbluefin/dakota-kernel-ubuntu/.github/workflows/build.yml@refs/heads/development' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
  "${IMAGE}@${DIGEST}"
```

The BST Docker source validates content digests; it does not perform this publisher-signature check for you.

## Consume with BuildStream 2

The `docker` source comes from [Apache buildstream-plugins](https://github.com/apache/buildstream-plugins/blob/master/src/buildstream_plugins/sources/docker.py), **not BuildStream's built-in plugins**. Install it into the environment that runs BST (inside your BST container if applicable):

```sh
python3 -m pip install 'buildstream-plugins==2.5.0'
```

Merge these entries into your consumer `project.conf`, preserving existing plugins and aliases:

```yaml
plugins:
- origin: pip
  package-name: buildstream-plugins==2.5.0
  sources:
  - docker

aliases:
  ghcr: https://ghcr.io/
```

After running the digest acquisition commands above, generate `elements/core/linux-ubuntu.bst`. This expands the **real** `KERNEL_REF` into valid YAML rather than asking you to copy an example digest:

```sh
mkdir -p elements/core
cat > elements/core/linux-ubuntu.bst <<EOF
kind: import
sources:
- kind: docker
  url: ghcr:projectbluefin/dakota-kernel-ubuntu
  architecture: amd64
  os: linux
  ref: ${KERNEL_REF}
public:
  bst:
    split-rules:
      devel:
      - /usr/src
      - /usr/src/**
      - /usr/lib/modules/*/build
      - /usr/lib/modules/*/System.map
      - /usr/lib/modules/*/vmlinux
      runtime:
      - /usr/lib/modules/*/vmlinuz
      - /usr/lib/modules/*/config
      - /usr/lib/modules/*/kernel/**
      - /usr/lib/modules/*/modules.*
EOF
```

Commit the resulting element/ref to your consumer repository. Optional `track: latest` under the Docker source enables `bst source track core/linux-ubuntu.bst` for intentional updates; review and commit the newly resolved ref before building. Without `track`, the digest stays fixed. Split patterns are absolute artifact paths, not shell globs relative to the element.

### Generic project wiring

An external-module builder uses the **whole imported artifact**, including its matching development split:

```yaml
build-depends:
- core/linux-ubuntu.bst
```

Add the kernel as a build dependency of your runtime `compose` element, alongside its existing OS inputs, and select runtime while excluding development:

```yaml
kind: compose
build-depends:
- core/linux-ubuntu.bst
# Add your existing runtime userspace/firmware/initramfs elements here.
config:
  include:
  - runtime
  exclude:
  - devel
  include-orphans: true
```

Keeping orphans includes files outside explicit splits, such as licensing metadata. The `devel` exclusion prevents headers, `System.map`, and `vmlinux` entering the runtime even if your project has broader inherited runtime rules. Retain whatever integration settings your existing composition needs.

Build an initramfs **in the consumer**, using this same kernel/module artifact plus that OS's userspace, firmware, and boot configuration. Importing the image does not generate one. Ensure the final composition includes both the kernel runtime and the consumer-generated initramfs.

### Dakota wiring

After publication and digest validation, replace/add Dakota's local `core/linux-ubuntu.bst` with the import above and route the freedesktop-sdk kernel at the **junction boundary**. In `elements/freedesktop-sdk.bst`, merge into the existing `config.overrides`:

```yaml
config:
  overrides:
    components/linux.bst: core/linux-ubuntu.bst
```

This keeps freedesktop-sdk's initramfs, unsigned-module handling, and NVIDIA module builder on the same kernel. Do not merely change the final image dependency: that can leave modules/initramfs built against another release. Remove or change any conditional `gaming` override of `components/linux.bst` if it would select a different kernel; retain unrelated junction overrides. Downstream cutover must wait for an actual published image.

External modules, especially NVIDIA, must be rebuilt against the imported headers, `.config`, and `Module.symvers` and installed under exactly the matching kernel release. Never combine headers/modules from another Ubuntu ABI or Dakota kernel. An RC kernel may be unsupported by a given NVIDIA driver even when its headers match; compatibility must be established remotely, not assumed. Secure Boot/module trust and production boot validation remain consumer responsibilities.

## Updating and corresponding source

The producer is a pinned source recipe, not an independently maintained kernel fork. For an update:

1. On a remote builder, run `just bst source track kernel.bst` to track `Ubuntu-7.3.0-*`; review and commit the source ref in `elements/kernel.bst`.
2. Update the expected release and all Ubuntu source identity fields in `.github/scripts/kernel-evidence.py`, OCI source version label in `elements/kernel-image.bst`, and this README when the Ubuntu ABI changes. The changelog determines the kernel's ABI suffix during the build; the verified receipt drives the registry labels and tag families.
3. For toolchain/configuration changes, update both `elements/dakota.bst` and the helper Git source in `elements/kernel.bst` to a reviewed full Dakota commit. Kernel updates do not require moving these pins.
4. Dispatch the remote workflow. After successful publication, acquire the new per-platform digest and update consumer refs together with external modules/initramfs.

For the current artifact, corresponding-source inputs are the [Ubuntu source tree at its exact commit](https://git.launchpad.net/~ubuntu-kernel/ubuntu/+source/linux/+git/stonking/tree/?id=d03cf7a92919b0e6ab4e4a756dec41542eb2040f), the [pinned Dakota tree](https://github.com/projectbluefin/dakota/tree/39d128aa9dfa66d73a6b48cefc70efdc1808766d) (toolchain and configuration helpers), and this producer repository at the commit identified by its immutable tag (kernel recipe and installation commands). These provide the source and scripts controlling compilation/installation; `/usr/src` alone does not. Preserve complete corresponding source and notices when redistributing binaries; links alone are not a substitute for fulfilling GPL source-distribution obligations.

## License

This project's original recipe/documentation and the kernel output are **GPL-2.0-only**; see [LICENSE](LICENSE), copied verbatim from the cached Ubuntu kernel's `LICENSES/preferred/GPL-2.0` license text. The kernel's [COPYING](https://git.launchpad.net/~ubuntu-kernel/ubuntu/+source/linux/+git/stonking/tree/COPYING?h=Ubuntu-7.3.0-8.8), [licensing rules](https://git.launchpad.net/~ubuntu-kernel/ubuntu/+source/linux/+git/stonking/tree/Documentation/process/license-rules.rst?h=Ubuntu-7.3.0-8.8), per-file SPDX notices and syscall exception remain authoritative for individual source/header files. Retain Ubuntu/Dakota configuration-script notices and any component-specific license terms; registry packaging does not erase them.
