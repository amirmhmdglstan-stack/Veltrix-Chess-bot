#!/usr/bin/env bash
# Veltrix 1.0 - build script for Linux / macOS
# Usage:
#   ./build.sh             - optimized build (portable baseline)
#   ./build.sh native      - fastest build for THIS CPU (-march=native)
#   ./build.sh avx2        - AVX2-optimized build
#   ./build.sh clean
set -e
cd "$(dirname "$0")/engine"

MODE="${1:-}"
case "$MODE" in
  clean)
    make clean
    exit 0
    ;;
  native)
    make NATIVE=1
    ;;
  avx2)
    make AVX2=1
    ;;
  *)
    make
    ;;
esac

mkdir -p ../bin
cp -f veltrix ../bin/veltrix
echo
echo "Veltrix built: engine/veltrix (also copied to bin/veltrix)"
echo "Try:  echo 'uci' | ./veltrix"
