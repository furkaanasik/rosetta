-- Rows with calibrate = 0 are ignored by estimator calibration (e.g. calls made with
-- unintended provider settings, such as an inherited thinking effort).
ALTER TABLE usage ADD COLUMN calibrate INTEGER NOT NULL DEFAULT 1;
