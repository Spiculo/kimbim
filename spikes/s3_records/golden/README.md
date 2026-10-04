# Golden hashes (spike S4)

Per-file `[state_hash, export_hash]` from the S3 record format (`kimcad-spike/1`), produced on Windows and Linux with ifcopenshell 0.9.0. They are identical for all 77 valid files.

The Rust implementation (milestone R1) uses these as golden values: same corpus file, same hashes. Any change to the record format must bump the format version and regenerate them.
