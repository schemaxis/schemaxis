"""Trusted fixed ImageJ 1.x program; authored values arrive only as checked arguments.

The JDK source-file launcher compiles this text in memory against ij.jar. It uses
public ImageJ classes only: PGM_Reader/Opener, Calibration, ImageProcessor
thresholds, ParticleAnalyzer with count masks, ResultsTable and ImageStatistics.
"""
NAME = 'SchemaxisImageJParticles.java'
PROGRAM = r'''import ij.IJ;
import ij.ImagePlus;
import ij.io.Opener;
import ij.measure.Calibration;
import ij.measure.Measurements;
import ij.measure.ResultsTable;
import ij.plugin.PGM_Reader;
import ij.plugin.filter.ParticleAnalyzer;
import ij.process.ByteProcessor;
import ij.process.ImageProcessor;
import ij.process.ImageStatistics;
import java.awt.Rectangle;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.util.LinkedHashMap;
import java.util.Map;

/** Fixed Schemaxis particle program. Authored input never becomes code. */
public class SchemaxisImageJParticles {
    static final String[] COLUMNS = {"Area", "Mean", "Min", "Max", "X", "Y", "BX", "BY", "Width", "Height"};
    static final int MEASUREMENTS = Measurements.AREA | Measurements.MEAN | Measurements.MIN_MAX
        | Measurements.CENTROID | Measurements.RECT;

    public static void main(String[] args) throws Exception {
        if (args.length == 13 && args[0].equals("analyse")) analyse(args);
        else if (args.length == 8 && args[0].equals("reopen")) reopen(args);
        else throw new IllegalArgumentException("unexpected fixed program arguments");
    }

    static String digest(String path) throws Exception {
        byte[] hash = MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(Paths.get(path)));
        StringBuilder text = new StringBuilder();
        for (byte value : hash) text.append(String.format("%02x", value & 255));
        return text.toString();
    }

    static String codepoints(String text) {
        StringBuilder result = new StringBuilder();
        for (int i = 0; i < text.length(); i++) result.append(i == 0 ? "" : ",").append((int)text.charAt(i));
        return result.toString();
    }

    static ImagePlus open(String path, String format) throws IOException {
        if (format.equals("pgm")) return new ImagePlus("input", new PGM_Reader().openFile(path));
        File file = new File(path);
        ImagePlus image = new Opener().openTiff(file.getParent() + File.separator, file.getName());
        if (image == null) throw new IOException("ImageJ could not decode the TIFF input");
        return image;
    }

    /** Record the decoded file state, then replace it with declared spatial calibration only. */
    static Map<String, String> calibrate(ImagePlus image, String stage, String input, String width, String height, String unit) throws Exception {
        Map<String, String> readback = new LinkedHashMap<>();
        Calibration file = image.getCalibration();
        readback.put("stage", stage);
        readback.put("imagej", IJ.getVersion());
        readback.put("java", System.getProperty("java.version"));
        readback.put("inputSha256", digest(input));
        readback.put("width", Integer.toString(image.getWidth()));
        readback.put("height", Integer.toString(image.getHeight()));
        readback.put("bitDepth", Integer.toString(image.getBitDepth()));
        readback.put("stackSize", Integer.toString(image.getStackSize()));
        readback.put("invertedLut", Boolean.toString(image.isInvertedLut()));
        readback.put("densityCalibrated", Boolean.toString(file.calibrated()));
        Calibration declared = new Calibration();
        declared.pixelWidth = Double.parseDouble(width);
        declared.pixelHeight = Double.parseDouble(height);
        declared.setUnit(unit);
        image.setCalibration(declared);
        Calibration observed = image.getCalibration();
        readback.put("pixelWidth", Double.toString(observed.pixelWidth));
        readback.put("pixelHeight", Double.toString(observed.pixelHeight));
        readback.put("unit", codepoints(observed.getUnit()));
        readback.put("yUnit", codepoints(observed.getYUnit()));
        readback.put("origin", Double.toString(observed.xOrigin) + "," + Double.toString(observed.yOrigin));
        return readback;
    }

    static void write(String name, String text) throws IOException {
        Files.write(Paths.get(name), text.getBytes(StandardCharsets.UTF_8));
    }

    static void writeReadback(String name, Map<String, String> readback) throws IOException {
        StringBuilder text = new StringBuilder();
        for (Map.Entry<String, String> entry : readback.entrySet()) text.append(entry.getKey()).append('=').append(entry.getValue()).append('\n');
        write(name, text.toString());
    }

    static void analyse(String[] args) throws Exception {
        ImagePlus image = open(args[1], args[2]);
        Map<String, String> readback = calibrate(image, "analyse", args[1], args[3], args[4], args[5]);
        ImageProcessor processor = image.getProcessor();
        processor.setThreshold(Integer.parseInt(args[6]), Integer.parseInt(args[7]), ImageProcessor.NO_LUT_UPDATE);
        readback.put("lowerThreshold", Double.toString(processor.getMinThreshold()));
        readback.put("upperThreshold", Double.toString(processor.getMaxThreshold()));
        int options = ParticleAnalyzer.SHOW_ROI_MASKS;
        // ImageJ includes holes for 4-connected tracing; set it explicitly because
        // the public constructor does not retain its own forced INCLUDE_HOLES flag.
        if (args[8].equals("four")) options |= ParticleAnalyzer.FOUR_CONNECTED | ParticleAnalyzer.INCLUDE_HOLES;
        else if (!args[8].equals("eight")) throw new IllegalArgumentException("connectivity");
        if (args[9].equals("1")) options |= ParticleAnalyzer.INCLUDE_HOLES;
        if (args[10].equals("1")) options |= ParticleAnalyzer.EXCLUDE_EDGE_PARTICLES;
        double minimum = Double.parseDouble(args[11]);
        double maximum = Double.parseDouble(args[12]);
        readback.put("options", Integer.toString(options));
        readback.put("minimumPixels", Double.toString(minimum));
        readback.put("maximumPixels", Double.toString(maximum));
        ResultsTable table = new ResultsTable();
        ParticleAnalyzer analyser = new ParticleAnalyzer(options, MEASUREMENTS, table, minimum, maximum);
        analyser.setHideOutputImage(true);
        if (!analyser.analyze(image, processor)) throw new IllegalStateException("ImageJ particle analysis did not complete");
        StringBuilder rows = new StringBuilder(String.join(",", COLUMNS)).append('\n');
        for (int row = 0; row < table.size(); row++) {
            for (int column = 0; column < COLUMNS.length; column++)
                rows.append(column == 0 ? "" : ",").append(Double.toString(table.getValue(COLUMNS[column], row)));
            rows.append('\n');
        }
        write("native-particles.csv", rows.toString());
        ImagePlus masks = analyser.getOutputImage();
        if (masks == null) throw new IllegalStateException("ImageJ did not create a count mask");
        ImageProcessor labels = masks.getProcessor();
        readback.put("particles", Integer.toString(table.size()));
        readback.put("maskBitDepth", Integer.toString(masks.getBitDepth()));
        ByteArrayOutputStream mask = new ByteArrayOutputStream();
        mask.write(("P5\n" + labels.getWidth() + " " + labels.getHeight() + "\n65535\n").getBytes(StandardCharsets.US_ASCII));
        for (int y = 0; y < labels.getHeight(); y++)
            for (int x = 0; x < labels.getWidth(); x++) {
                int value = labels.get(x, y);
                mask.write(value >> 8);
                mask.write(value & 255);
            }
        Files.write(Paths.get("count-mask.pgm"), mask.toByteArray());
        writeReadback("analyse-readback.txt", readback);
    }

    /** Fresh process: decode the retained count mask and re-measure each label with ImageStatistics. */
    static void reopen(String[] args) throws Exception {
        ImagePlus image = open(args[1], args[2]);
        Map<String, String> readback = calibrate(image, "reopen", args[1], args[3], args[4], args[5]);
        ImagePlus masks = new ImagePlus("labels", new PGM_Reader().openFile(args[6]));
        readback.put("maskSha256", digest(args[6]));
        readback.put("maskBitDepth", Integer.toString(masks.getBitDepth()));
        ImageProcessor labels = masks.getProcessor();
        ImageProcessor processor = image.getProcessor();
        if (labels.getWidth() != processor.getWidth() || labels.getHeight() != processor.getHeight())
            throw new IllegalStateException("count mask dimensions differ");
        int count = Integer.parseInt(args[7]);
        int[][] bounds = new int[count + 1][];
        for (int y = 0; y < labels.getHeight(); y++)
            for (int x = 0; x < labels.getWidth(); x++) {
                int value = labels.get(x, y);
                if (value == 0) continue;
                if (value > count) throw new IllegalStateException("count mask label exceeds particle count");
                int[] box = bounds[value];
                if (box == null) bounds[value] = new int[] {x, y, x, y};
                else {
                    box[0] = Math.min(box[0], x); box[1] = Math.min(box[1], y);
                    box[2] = Math.max(box[2], x); box[3] = Math.max(box[3], y);
                }
            }
        StringBuilder rows = new StringBuilder(String.join(",", COLUMNS)).append('\n');
        for (int label = 1; label <= count; label++) {
            int[] box = bounds[label];
            if (box == null) throw new IllegalStateException("count mask omits a particle label");
            Rectangle rectangle = new Rectangle(box[0], box[1], box[2] - box[0] + 1, box[3] - box[1] + 1);
            ByteProcessor selection = new ByteProcessor(rectangle.width, rectangle.height);
            for (int y = 0; y < rectangle.height; y++)
                for (int x = 0; x < rectangle.width; x++)
                    if (labels.get(rectangle.x + x, rectangle.y + y) == label) selection.set(x, y, 255);
            processor.setRoi(rectangle);
            processor.setMask(selection);
            ImageStatistics statistics = ImageStatistics.getStatistics(processor, MEASUREMENTS, image.getCalibration());
            double[] values = {statistics.area, statistics.mean, statistics.min, statistics.max,
                statistics.xCentroid, statistics.yCentroid, statistics.roiX, statistics.roiY,
                statistics.roiWidth, statistics.roiHeight};
            for (int column = 0; column < values.length; column++)
                rows.append(column == 0 ? "" : ",").append(Double.toString(values[column]));
            rows.append('\n');
        }
        readback.put("particles", Integer.toString(count));
        write("reopen-particles.csv", rows.toString());
        writeReadback("reopen-readback.txt", readback);
    }
}
'''
