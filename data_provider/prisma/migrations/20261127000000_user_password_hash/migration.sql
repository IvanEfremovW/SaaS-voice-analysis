-- AlterTable
-- Users created before this migration get an empty hash, which matches no password: they can't log in
-- until an admin sets their password (PUT /users/:id/password). New users always get one.
ALTER TABLE "users" ADD COLUMN     "password_hash" TEXT NOT NULL DEFAULT '';
ALTER TABLE "users" ALTER COLUMN "password_hash" DROP DEFAULT;
