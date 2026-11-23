-- AlterTable
ALTER TABLE "file" ADD COLUMN     "checksum" TEXT NOT NULL;

-- CreateIndex
CREATE UNIQUE INDEX "file_checksum_key" ON "file"("checksum");

