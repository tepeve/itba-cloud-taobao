# script para descargar el dataset de UserBehavior desde Google Drive
FILE_ID="19S4jCcQe5CDxwCEraQ17_s6k0WjtpRAT"
OUTPUT="data/raw/UserBehavior.csv"

if [ -s "$OUTPUT" ]; then
    echo "Dataset ya descargado en $OUTPUT"
    exit 0
fi

HTML_RESPONSE=$(curl -c ./cookies.txt -s -L "https://drive.google.com/uc?export=download&id=${FILE_ID}")
CONFIRM_TOKEN=$(echo "$HTML_RESPONSE" | grep -o -E 'confirm=[^&"]+' | head -n 1 | cut -d '=' -f 2)

if [ -n "$CONFIRM_TOKEN" ]; then
    curl -Lb ./cookies.txt "https://drive.usercontent.google.com/download?id=${FILE_ID}&confirm=${CONFIRM_TOKEN}&export=download" -o "$OUTPUT"
else
    curl -Lb ./cookies.txt "https://drive.usercontent.google.com/download?id=${FILE_ID}&export=download&confirm=t" -o "$OUTPUT"
fi

rm -f ./cookies.txt