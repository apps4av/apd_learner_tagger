Adopted from Mike Rieker's C# script

# apd_learner_tagger

Georeferences FAA airport diagrams and publishes `avare_aptdiags.php` for the tpp build.

The scheduled run starts at 05:00 America/New_York on the Sunday of an FAA release week, two hours before tpp. It writes the file to `https://www.apps4av.org/new/staging/avare_aptdiags.php`.

```bash
./run.sh
```

Learning mode updates the character templates from a diagram whose labels you already know. Run it in the directory that contains `ReadArptDgmPng_learnt.csv`. Each diagram adds to that file.

```bash
python3 read_arpt_dgm_png.py diagram.png -givens "1497,2141=79^56.5'W" "1497,1485=79^56.0'W"
```

`diagram.png` is page 1 of the airport-diagram PDF rendered at 300 dpi.
