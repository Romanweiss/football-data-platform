"""Isolated Spark worker; invoked by the explicit local ETL coordinator only."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.openfootball_etl.spark_job import main

if __name__ == "__main__":
    main()
