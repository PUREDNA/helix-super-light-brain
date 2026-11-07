#!/bin/sh
# Lægger en kopi af DNA's Obsidian ind i hjernens EGEN volume.
#
# Modellen er den samme som for databaserne: hjernen har sit eget lager i sin
# egen volume. DNA's private mappe læses KUN — den røres aldrig, og den er ikke
# monteret ind i containeren.
#
# Brug:
#   sh scripts/kopi_obsidian.sh                      # fra /home/dna/Obsidian
#   sh scripts/kopi_obsidian.sh /anden/sti/Obsidian  # fra en anden mappe
#
# Kopien kan køres igen: den spejler kilden (sletter ikke i kilden, men rydder
# målet først, så en slettet note også forsvinder i kopien).
set -e
KILDE="${1:-/home/dna/Obsidian}"
VOLUMEN="${VOLUMEN:-helix_obsidian_data}"

if [ ! -d "$KILDE" ]; then
  echo "kilden findes ikke: $KILDE" >&2
  exit 1
fi

docker volume create "$VOLUMEN" >/dev/null

echo "kopierer '$KILDE' -> volume '$VOLUMEN' (kun læsning af kilden) ..."
docker run --rm -v "$KILDE":/kilde:ro -v "$VOLUMEN":/maal alpine sh -c '
  rm -rf /maal/* /maal/.[!.]* 2>/dev/null || true      # spejl kilden
  cp -a /kilde/. /maal/
  chown -R 999:999 /maal                                # postgres kan læse OG skrive
'

echo -n "  filer i kilden:  "; find "$KILDE" -type f | wc -l
docker run --rm -v "$VOLUMEN":/maal alpine sh -c '
  printf "  filer i kopien:  "; find /maal -type f | wc -l
  printf "  noter (.md):     "; find /maal -name "*.md" | wc -l
  printf "  størrelse:       "; du -sh /maal | cut -f1
'
echo "klar. Genstart containeren for at den ser kopien:  docker compose up -d"
