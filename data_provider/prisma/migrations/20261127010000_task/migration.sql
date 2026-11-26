-- CreateEnum
CREATE TYPE "TaskType" AS ENUM ('TRANSCRIPTION', 'ANALYSIS');

-- CreateEnum
CREATE TYPE "TaskStatus" AS ENUM ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED');

-- CreateTable
CREATE TABLE "task" (
    "id" TEXT NOT NULL,
    "call_id" TEXT NOT NULL,
    "type" "TaskType" NOT NULL,
    "status" "TaskStatus" NOT NULL DEFAULT 'QUEUED',
    "metadata" JSONB NOT NULL DEFAULT '{}',
    "error" TEXT,
    "started_at" TIMESTAMP(3),
    "finished_at" TIMESTAMP(3),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "task_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "task_call_id_idx" ON "task"("call_id");

-- CreateIndex
CREATE INDEX "task_status_idx" ON "task"("status");

-- AddForeignKey
ALTER TABLE "task" ADD CONSTRAINT "task_call_id_fkey" FOREIGN KEY ("call_id") REFERENCES "call"("id") ON DELETE CASCADE ON UPDATE CASCADE;

