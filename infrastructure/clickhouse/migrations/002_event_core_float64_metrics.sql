ALTER TABLE football.event_core
MODIFY COLUMN location_x Nullable(Float64),
MODIFY COLUMN location_y Nullable(Float64),
MODIFY COLUMN duration Nullable(Float64);
