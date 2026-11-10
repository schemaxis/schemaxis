"""Trusted fixed ImageJ 1.x region-measurement program; authored values arrive only as checked data.

The JDK source-file launcher compiles this text in memory against ij.jar. It uses public
ImageJ classes only: PGM_Reader/Opener, ImagePlus/ImageStack, Roi, Calibration,
ImageProcessor and ImageStatistics. It reads a host-written specification file whose
identifiers are validated literals; no authored text is executed, no GUI RoiManager,
macro, plugin or reflection is used.
"""
NAME = 'SchemaxisImageJRegions.java'
PROGRAM = r'''import ij.IJ;
import ij.ImagePlus;
import ij.ImageStack;
import ij.gui.Roi;
import ij.io.Opener;
import ij.measure.Calibration;
import ij.measure.Measurements;
import ij.plugin.PGM_Reader;
import ij.process.ImageProcessor;
import ij.process.ImageStatistics;
import java.awt.Rectangle;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.List;

/** Fixed Schemaxis region-series program. Authored input never becomes code. */
public class SchemaxisImageJRegions {
    static final int MEASUREMENTS = Measurements.AREA | Measurements.MEAN | Measurements.MIN_MAX | Measurements.RECT;
    static final String HEADER = "Frame,Region,X,Y,Width,Height,Count,Area,Mean,Min,Max";

    public static void main(String[] args) throws Exception {
        if (args.length == 5 && (args[0].equals("measure") || args[0].equals("reopen"))) run(args);
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
        for (int i = 0; i < text.length(); i++) result.append(i == 0 ? "" : ",").append((int) text.charAt(i));
        return result.toString();
    }

    static ImagePlus open(String path, String format) throws IOException {
        if (format.equals("pgm")) return new ImagePlus("input", new PGM_Reader().openFile(path));
        File file = new File(path);
        ImagePlus image = new Opener().openTiff(file.getParent() + File.separator, file.getName());
        if (image == null) throw new IOException("ImageJ could not decode the TIFF input");
        return image;
    }

    static void line(StringBuilder text, String key, String value) {
        text.append(key).append('=').append(value).append('\n');
    }

    static void run(String[] args) throws Exception {
        String stage = args[0];
        List<String[]> frames = new ArrayList<>();
        List<String[]> regions = new ArrayList<>();
        for (String text : Files.readAllLines(Paths.get(args[1]), StandardCharsets.UTF_8)) {
            String[] fields = text.split(" ", -1);
            if (fields[0].equals("frame") && fields.length == 5) frames.add(fields);
            else if (fields[0].equals("region") && fields.length == 6) regions.add(fields);
            else throw new IllegalArgumentException("series specification line");
        }
        StringBuilder readback = new StringBuilder();
        line(readback, "stage", stage);
        line(readback, "imagej", IJ.getVersion());
        line(readback, "java", System.getProperty("java.version"));
        line(readback, "jarSha256", digest(System.getProperty("java.class.path")));
        line(readback, "frames", Integer.toString(frames.size()));
        line(readback, "regions", Integer.toString(regions.size()));
        ImageStack stack = null;
        StringBuilder planes = new StringBuilder();
        for (int index = 0; index < frames.size(); index++) {
            String[] frame = frames.get(index);
            String path = new File(frame[3]).getAbsolutePath();
            ImagePlus image = open(path, frame[4]);
            Calibration file = image.getCalibration();
            String key = "frame." + index + ".";
            line(planes, key + "sha256", digest(path));
            line(planes, key + "width", Integer.toString(image.getWidth()));
            line(planes, key + "height", Integer.toString(image.getHeight()));
            line(planes, key + "bitDepth", Integer.toString(image.getBitDepth()));
            line(planes, key + "stackSize", Integer.toString(image.getStackSize()));
            line(planes, key + "invertedLut", Boolean.toString(image.isInvertedLut()));
            line(planes, key + "densityCalibrated", Boolean.toString(file.calibrated()));
            line(planes, key + "fileCalibration", Double.toString(file.pixelWidth) + ","
                + Double.toString(file.pixelHeight) + "," + codepoints(file.getUnit()));
            if (stack == null) stack = new ImageStack(image.getWidth(), image.getHeight());
            stack.addSlice(frame[1], image.getProcessor());
        }
        ImagePlus series = new ImagePlus("series", stack);
        Calibration declared = new Calibration();
        declared.pixelWidth = Double.parseDouble(args[2]);
        declared.pixelHeight = Double.parseDouble(args[3]);
        declared.setUnit(args[4]);
        series.setCalibration(declared);
        Calibration observed = series.getCalibration();
        line(readback, "stackSize", Integer.toString(series.getStackSize()));
        line(readback, "pixelWidth", Double.toString(observed.pixelWidth));
        line(readback, "pixelHeight", Double.toString(observed.pixelHeight));
        line(readback, "unit", codepoints(observed.getUnit()));
        line(readback, "yUnit", codepoints(observed.getYUnit()));
        line(readback, "origin", Double.toString(observed.xOrigin) + "," + Double.toString(observed.yOrigin));
        readback.append(planes);
        for (int index = 0; index < frames.size(); index++)
            line(readback, "label." + index, series.getStack().getSliceLabel(index + 1));
        StringBuilder rows = new StringBuilder(HEADER).append('\n');
        List<String> rois = new ArrayList<>();
        for (int region = 0; region < regions.size(); region++) {
            String[] fields = regions.get(region);
            Roi probe = new Roi(Integer.parseInt(fields[2]), Integer.parseInt(fields[3]),
                Integer.parseInt(fields[4]), Integer.parseInt(fields[5]));
            probe.setName(fields[1]);
            Rectangle bounds = probe.getBounds();
            rois.add("region." + region + "=" + probe.getName() + "," + bounds.x + "," + bounds.y + ","
                + bounds.width + "," + bounds.height + "," + probe.getTypeAsString());
        }
        for (int frame = 0; frame < frames.size(); frame++) {
            for (int region = 0; region < regions.size(); region++) {
                String[] fields = regions.get(region);
                Roi roi = new Roi(Integer.parseInt(fields[2]), Integer.parseInt(fields[3]),
                    Integer.parseInt(fields[4]), Integer.parseInt(fields[5]));
                ImageStatistics statistics;
                if (stage.equals("measure")) {
                    ImageProcessor processor = series.getStack().getProcessor(frame + 1);
                    processor.setRoi(roi);
                    statistics = ImageStatistics.getStatistics(processor, MEASUREMENTS, series.getCalibration());
                } else {
                    series.setSlice(frame + 1);
                    series.setRoi(roi);
                    statistics = series.getStatistics(MEASUREMENTS);
                }
                rows.append(frame).append(',').append(region).append(',')
                    .append(Double.toString(statistics.roiX)).append(',').append(Double.toString(statistics.roiY)).append(',')
                    .append(Double.toString(statistics.roiWidth)).append(',').append(Double.toString(statistics.roiHeight)).append(',')
                    .append(statistics.pixelCount).append(',').append(Double.toString(statistics.area)).append(',')
                    .append(Double.toString(statistics.mean)).append(',').append(Double.toString(statistics.min)).append(',')
                    .append(Double.toString(statistics.max)).append('\n');
            }
        }
        for (String roi : rois) readback.append(roi).append('\n');
        Files.write(Paths.get(stage.equals("measure") ? "native-measurements.csv" : "reopen-measurements.csv"),
            rows.toString().getBytes(StandardCharsets.UTF_8));
        Files.write(Paths.get(stage + "-readback.txt"), readback.toString().getBytes(StandardCharsets.UTF_8));
    }
}
'''
