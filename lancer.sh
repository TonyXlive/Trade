#!/bin/sh
cd "$(dirname "$0")"
python3 -m bot.main --monte-carlo 100
echo "Ouvrez sortie/rapport.html dans votre navigateur."
