"""PDF presentation parser and slide text/metadata extractor."""
import os
from pathlib import Path
from typing import List, Dict, Any, Tuple
import pypdf

from src.models.slide import Slide, SlideReviewStatus
from src.backend.slides.slide_validator import SlideValidator
from src.utils.logging_config import setup_logger

logger = setup_logger("pdf_parser")


class PDFPresentationParser:
    """Parses PDF presentation decks, extracting slide texts, bookmarks, and metadata."""

    def __init__(self, pdf_path: str | Path):
        self.pdf_path = Path(pdf_path).resolve()
        if not self.pdf_path.is_file():
            raise FileNotFoundError(f"PDF presentation file not found: {self.pdf_path}")

    def inspect_presentation(self) -> Dict[str, Any]:
        """Perform quick high-level analysis of the presentation."""
        reader = pypdf.PdfReader(str(self.pdf_path))
        num_pages = len(reader.pages)
        title = self.pdf_path.stem.replace("_", " ")

        if reader.metadata and reader.metadata.title:
            title = reader.metadata.title

        return {
            "file_name": self.pdf_path.name,
            "file_path": str(self.pdf_path),
            "file_size_bytes": self.pdf_path.stat().st_size,
            "slide_count": num_pages,
            "title": title,
        }

    def parse_slides(self) -> Tuple[List[Slide], Dict[str, Any]]:
        """Extract all slides and build initial Slide objects with analysis metrics."""
        reader = pypdf.PdfReader(str(self.pdf_path))
        num_pages = len(reader.pages)
        slides: List[Slide] = []

        total_words = 0
        empty_slides = 0
        image_only_slides = 0

        for i, page in enumerate(reader.pages):
            slide_num = i + 1
            slide_id = f"slide_{slide_num:03d}"

            # Extract raw text
            text = (page.extract_text() or "").strip()
            lines = [line.strip() for line in text.splitlines() if line.strip()]

            # Determine title: first non-empty line or fallback
            title = f"Slide {slide_num}"
            if lines:
                title_candidate = lines[0]
                # If first line is a header like 'DAY 1 OF 7' and second line exists, use combined or second
                if len(lines) > 1 and len(title_candidate) < 40 and any(keyword in title_candidate.lower() for keyword in ["day", "part", "module", "chapter", "lesson", "unit", "week"]):
                    title = lines[1]
                else:
                    title = title_candidate[:80]

            words = text.split()
            word_count = len(words)
            total_words += word_count

            # Check for embedded images
            num_images = len(page.images) if hasattr(page, "images") else 0
            is_image_only = (num_images > 0 and word_count < 10)
            is_empty = (word_count == 0 and num_images == 0)

            if is_empty:
                empty_slides += 1
            if is_image_only:
                image_only_slides += 1

            slide = Slide(
                slide_id=slide_id,
                slide_number=slide_num,
                title=title,
                original_text=text,
                notes="",  # Speaker notes if any
                review_status=SlideReviewStatus.REVIEW_REQUIRED,
                duration_estimate=round(max(5.0, (word_count / 140.0) * 60), 1),
                word_count=word_count,
                mode="original",
                is_empty=is_empty,
                is_image_only=is_image_only,
                metadata={
                    "num_images": num_images,
                    "extracted_lines_count": len(lines),
                },
            )

            SlideValidator.analyze_slide(slide)
            slides.append(slide)

        summary = {
            "slide_count": num_pages,
            "total_words": total_words,
            "empty_slides": empty_slides,
            "image_only_slides": image_only_slides,
            "average_words_per_slide": round(total_words / max(num_pages, 1), 1),
        }

        logger.info(f"Parsed {num_pages} slides from {self.pdf_path.name}: {total_words} words total.")
        return slides, summary
